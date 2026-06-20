"""
TCGA GDC-client data extractor agent.

Goal: enumerate every publicly available data modality for a TCGA project
(default TCGA-LUAD) via the GDC search API, then use the GDC Data Transfer
Tool (./gdc-client, sibling file) to download files for each modality, organised by
cancer type. Test mode pulls 5 distinct cases per data type; flip
DOWNLOAD_ALL_SAMPLES to True (or set env var DOWNLOAD_ALL_SAMPLES=1) to
pull every open-access file for every data type.

Architecture (mirrors tcga_extractor_agent.py):
  - Hand-rolled OpenAI-tool-calling loop against the Argo Gateway (gpt54).
  - Tools query GDC's REST API (urllib) for file discovery, then shell out
    to ./gdc-client (sibling file) for the actual downloads. No R, no TCGAbiolinks.

Output layout (cancer-type rooted; data_category/data_type nested):
  <OUT_ROOT>/<CANCER_TYPE>/<data_category>/<data_type>/<file_id>/<file>
  <OUT_ROOT>/<CANCER_TYPE>/<data_category>/<data_type>/_manifest.txt
  <OUT_ROOT>/<CANCER_TYPE>/modalities_cache.json
  <OUT_ROOT>/<CANCER_TYPE>/summary.md

Run:
    conda run -n biomni_e1 --no-capture-output python -u have/data/tcga/scripts/tcga_gdc_client_agent.py

Env vars (all optional):
    DOWNLOAD_ALL_SAMPLES        "1"/"true" to bypass every cap and pull all
                                files of every data type (overrides the
                                top-of-file constant).
    ARGO_USER                   ANL domain username (default: yitan.zhu)
    ARGO_MODEL                  Argo model name     (default: gpt54)
    TCGA_PROJECT                TCGA project id     (default: TCGA-LUAD)
    TCGA_GDC_OUTPUT_ROOT        output root         (default: have/data/tcga/data/_gdc_client)
    TCGA_GDC_MAX_CASES          per-modality case cap (default: 5; 0 / "unlimited" = no cap)
    TCGA_GDC_MAX_MODALITIES     limit modalities profiled this run (default: unlimited)
    TCGA_GDC_FULL_BYTES_THRESHOLD   tiny-modality byte cutoff to auto-download
                                    everything (default: 500_000_000)
    TCGA_GDC_FULL_FILES_THRESHOLD   tiny-modality file-count cutoff (default: 50)
    TCGA_GDC_FORCE_RELIST       bypass modalities_cache.json (default: off)
    TCGA_GDC_EXCLUDE            comma/semicolon-separated list of modalities
                                to skip. Each entry is either a bare data_type
                                ("Slide Image") which matches any category, or
                                "data_category/data_type" for an exact match.
                                Example: "Slide Image,DNA Methylation/Masked Intensities"
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Env helpers (defined before the master switch)
# ---------------------------------------------------------------------------
def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


# ===========================================================================
# MASTER SWITCH — flip to True (or set env var DOWNLOAD_ALL_SAMPLES=1) to
# pull every open-access file for every data type of the project. With
# False (default), the agent runs in test mode: 5 distinct cases per data
# type, with a size-based override that auto-downloads small modalities in
# full.
# ===========================================================================
DOWNLOAD_ALL_SAMPLES: bool = _env_true("DOWNLOAD_ALL_SAMPLES", default=False)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER     = os.environ.get("ARGO_USER",  "yitan.zhu")
ARGO_MODEL    = os.environ.get("ARGO_MODEL", "gpt54")

TCGA_PROJECT     = os.environ.get("TCGA_PROJECT", "TCGA-LUAD")
SCRIPT_DIR       = Path(__file__).resolve().parent
DEFAULT_ROOT     = SCRIPT_DIR.parent / "data" / "_gdc_client"   # have/data/tcga/data/_gdc_client/
TCGA_GDC_OUTPUT_ROOT = Path(
    os.environ.get("TCGA_GDC_OUTPUT_ROOT", str(DEFAULT_ROOT))
).resolve()

GDC_CLIENT_PATH = SCRIPT_DIR / "gdc-client"
GDC_API_BASE    = "https://api.gdc.cancer.gov"


def _parse_int_cap(raw: str | None, default: int | None) -> int | None:
    """None = no cap. Accepts '0', '', 'unlimited', 'all' as no-cap signals."""
    if raw is None:
        return default
    s = raw.strip().lower()
    if s == "":
        return default
    try:
        n = int(s)
    except ValueError:
        return None
    return None if n <= 0 else n


TCGA_GDC_MAX_CASES      = _parse_int_cap(os.environ.get("TCGA_GDC_MAX_CASES"),      default=5)
TCGA_GDC_MAX_MODALITIES = _parse_int_cap(os.environ.get("TCGA_GDC_MAX_MODALITIES"), default=None)
TCGA_GDC_FULL_BYTES_THRESHOLD = int(
    os.environ.get("TCGA_GDC_FULL_BYTES_THRESHOLD", str(500_000_000))
)
TCGA_GDC_FULL_FILES_THRESHOLD = int(
    os.environ.get("TCGA_GDC_FULL_FILES_THRESHOLD", "50")
)


def _parse_exclude_list(raw: str | None) -> list[tuple[str | None, str]]:
    """Parse TCGA_GDC_EXCLUDE into [(category_or_None, data_type), ...].
    Entries are split on comma or semicolon. An entry containing "/" is
    treated as "category/type" (exact pair); otherwise it matches the data
    type alone, in any category."""
    if not raw:
        return []
    rules: list[tuple[str | None, str]] = []
    for piece in re.split(r"[,;]", raw):
        s = piece.strip()
        if not s:
            continue
        if "/" in s:
            cat, dtp = s.split("/", 1)
            rules.append((cat.strip(), dtp.strip()))
        else:
            rules.append((None, s))
    return rules


TCGA_GDC_EXCLUDE = _parse_exclude_list(os.environ.get("TCGA_GDC_EXCLUDE"))


def _is_excluded(category: str, dtp: str) -> bool:
    for rule_cat, rule_dtp in TCGA_GDC_EXCLUDE:
        if rule_dtp == dtp and (rule_cat is None or rule_cat == category):
            return True
    return False


# Master switch overrides per-knob caps (but NOT the exclude list — the user
# may still want to skip oversized modalities even during a full pull).
if DOWNLOAD_ALL_SAMPLES:
    TCGA_GDC_MAX_CASES      = None
    TCGA_GDC_MAX_MODALITIES = None

# Cancer-type folder name: "TCGA-LUAD" -> "LUAD"; non-TCGA ids -> raw id.
CANCER_TYPE = TCGA_PROJECT.split("-", 1)[1] if TCGA_PROJECT.startswith("TCGA-") else TCGA_PROJECT

TCGA_GDC_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
CANCER_TYPE_DIR = TCGA_GDC_OUTPUT_ROOT / CANCER_TYPE
SUMMARY_PATH    = CANCER_TYPE_DIR / "summary.md"

client = OpenAI(base_url=ARGO_BASE_URL, api_key=ARGO_USER)


# ---------------------------------------------------------------------------
# Coverage tracking — guarantees every modality is downloaded before the
# agent is allowed to write the final summary.
# ---------------------------------------------------------------------------
def _sanitize(x: str | None) -> str:
    if x is None or x == "":
        return "default"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", x)


EXPECTED_MODALITIES: list[dict] = []
DOWNLOADED: set[tuple] = set()  # (data_category, data_type)


# ---------------------------------------------------------------------------
# GDC REST API helpers (no external `requests` dependency)
# ---------------------------------------------------------------------------
def _gdc_post(endpoint: str, body: dict, timeout: int = 300) -> dict:
    url  = f"{GDC_API_BASE}/{endpoint.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gdc_paginated_files(filters: dict, fields: str, page_size: int = 5000) -> list[dict]:
    rows: list[dict] = []
    from_idx = 0
    while True:
        body = {
            "filters": filters,
            "fields":  fields,
            "format":  "json",
            "size":    str(page_size),
            "from":    str(from_idx),
        }
        resp = _gdc_post("files", body)
        hits = resp.get("data", {}).get("hits", []) or []
        rows.extend(hits)
        pagination = resp.get("data", {}).get("pagination", {}) or {}
        total = int(pagination.get("total", 0))
        print(f"  [api] pulled {len(rows)}/{total}", file=sys.stderr, flush=True)
        if len(rows) >= total or not hits:
            break
        from_idx += page_size
    return rows


# ---------------------------------------------------------------------------
# File-level metadata sidecar (one row per file; multi-value fields like
# samples/aliquots are deduplicated and semicolon-joined within the cell).
# ---------------------------------------------------------------------------
# Fields we request from the GDC API per file. Dot-paths follow the GDC
# schema (analysis.workflow_*, cases.*, cases.samples.*, aliquots.*).
_METADATA_FIELDS = ",".join([
    "file_id", "file_name", "file_size", "md5sum",
    "data_category", "data_type", "data_format",
    "experimental_strategy", "platform", "access",
    "created_datetime", "updated_datetime",
    "analysis.workflow_type", "analysis.workflow_version",
    "cases.case_id", "cases.submitter_id",
    "cases.project.project_id",
    "cases.samples.sample_id", "cases.samples.submitter_id",
    "cases.samples.sample_type",
    "cases.samples.portions.analytes.aliquots.aliquot_id",
    "cases.samples.portions.analytes.aliquots.submitter_id",
])

# Output column order for the TSV. One row per file. Multi-valued fields
# (case/sample/aliquot identifiers when a single file is linked to several)
# are semicolon-joined after deduplication.
METADATA_COLUMNS = [
    "file_uuid", "file_name", "file_size", "md5sum",
    "project", "data_category", "data_type", "data_format",
    "experimental_strategy", "platform", "access",
    "workflow_type", "workflow_version",
    "case_uuid", "patient_id",
    "sample_uuid", "sample_barcode", "sample_type",
    "aliquot_uuid", "aliquot_barcode",
    "n_cases", "n_samples", "n_aliquots",
    "created_datetime", "updated_datetime",
]


def _fetch_file_metadata(file_ids: list[str]) -> list[dict]:
    """Query GDC for rich metadata of the given file UUIDs. Batched at 500
    UUIDs/request — the API enforces a request-body size limit."""
    out: list[dict] = []
    batch_size = 500
    for i in range(0, len(file_ids), batch_size):
        batch = file_ids[i:i + batch_size]
        body = {
            "filters": {"op": "in",
                        "content": {"field": "file_id", "value": batch}},
            "fields":  _METADATA_FIELDS,
            "format":  "json",
            "size":    str(len(batch)),
        }
        resp = _gdc_post("files", body)
        out.extend(resp.get("data", {}).get("hits", []) or [])
    return out


def _uniq_join(values, sep: str = ";"):
    """Deduplicate (preserve first-seen order), drop None/empty, semicolon-join.
    Returns None when no values remain so the TSV cell stays blank."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v is None or v == "":
            continue
        s = str(v)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return sep.join(out) if out else None


def _metadata_row_for_file(hit: dict) -> dict:
    """Build ONE row for a file. case/sample/aliquot identifiers are collected
    across every linked entity and semicolon-joined within the cell."""
    analysis = hit.get("analysis") or {}
    projects:        list = []
    case_uuids:      list = []
    patient_ids:     list = []
    sample_uuids:    list = []
    sample_barcodes: list = []
    sample_types:    list = []
    aliquot_uuids:   list = []
    aliquot_barcodes: list = []

    for c in (hit.get("cases") or []):
        case_uuids.append(c.get("case_id"))
        patient_ids.append(c.get("submitter_id"))
        proj = (c.get("project") or {}).get("project_id")
        if proj:
            projects.append(proj)
        for s in (c.get("samples") or []):
            sample_uuids.append(s.get("sample_id"))
            sample_barcodes.append(s.get("submitter_id"))
            sample_types.append(s.get("sample_type"))
            for portion in (s.get("portions") or []):
                for analyte in (portion.get("analytes") or []):
                    for a in (analyte.get("aliquots") or []):
                        aliquot_uuids.append(a.get("aliquot_id"))
                        aliquot_barcodes.append(a.get("submitter_id"))

    def _n_unique(values) -> int:
        return len({v for v in values if v})

    return {
        "file_uuid":             hit.get("file_id"),
        "file_name":             hit.get("file_name"),
        "file_size":             hit.get("file_size"),
        "md5sum":                hit.get("md5sum"),
        "project":               _uniq_join(projects),
        "data_category":         hit.get("data_category"),
        "data_type":             hit.get("data_type"),
        "data_format":           hit.get("data_format"),
        "experimental_strategy": hit.get("experimental_strategy"),
        "platform":              hit.get("platform"),
        "access":                hit.get("access"),
        "workflow_type":         analysis.get("workflow_type"),
        "workflow_version":      analysis.get("workflow_version"),
        "case_uuid":             _uniq_join(case_uuids),
        "patient_id":            _uniq_join(patient_ids),
        "sample_uuid":           _uniq_join(sample_uuids),
        "sample_barcode":        _uniq_join(sample_barcodes),
        "sample_type":           _uniq_join(sample_types),
        "aliquot_uuid":          _uniq_join(aliquot_uuids),
        "aliquot_barcode":       _uniq_join(aliquot_barcodes),
        "n_cases":               _n_unique(case_uuids),
        "n_samples":             _n_unique(sample_uuids),
        "n_aliquots":            _n_unique(aliquot_uuids),
        "created_datetime":      hit.get("created_datetime"),
        "updated_datetime":      hit.get("updated_datetime"),
    }


def _write_metadata_tsv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("\t".join(METADATA_COLUMNS) + "\n")
        for r in rows:
            cells = []
            for col in METADATA_COLUMNS:
                v = r.get(col)
                if v is None:
                    cells.append("")
                else:
                    # Defensive: TSV-safe — strip tabs/newlines from values.
                    cells.append(str(v).replace("\t", " ").replace("\r", " ")
                                       .replace("\n", " "))
            f.write("\t".join(cells) + "\n")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def list_gdc_data_types(project: str) -> str:
    """Enumerate every open-access (data_category, data_type) modality
    available for the project. Cached on disk per cancer-type."""
    global EXPECTED_MODALITIES
    cache_path = CANCER_TYPE_DIR / "modalities_cache.json"
    if cache_path.exists() and not os.environ.get("TCGA_GDC_FORCE_RELIST"):
        print(f"  [cache] using {cache_path}", file=sys.stderr, flush=True)
        result = json.loads(cache_path.read_text())
    else:
        filters = {
            "op": "and",
            "content": [
                {"op": "=", "content": {"field": "cases.project.project_id", "value": project}},
                {"op": "=", "content": {"field": "files.access",             "value": "open"}},
            ],
        }
        rows = _gdc_paginated_files(
            filters, fields="file_id,file_size,data_category,data_type,cases.case_id"
        )
        agg: dict[tuple, dict] = {}
        for r in rows:
            cat = r.get("data_category") or "Unknown"
            dtp = r.get("data_type")     or "Unknown"
            key = (cat, dtp)
            if key not in agg:
                agg[key] = {
                    "data_category": cat,
                    "data_type":     dtp,
                    "total_files":   0,
                    "total_bytes":   0,
                    "_case_ids":     set(),
                }
            agg[key]["total_files"] += 1
            agg[key]["total_bytes"] += int(r.get("file_size") or 0)
            for c in (r.get("cases") or []):
                cid = c.get("case_id")
                if cid:
                    agg[key]["_case_ids"].add(cid)
        modalities = []
        for entry in agg.values():
            entry["n_cases_total"] = len(entry.pop("_case_ids"))
            modalities.append(entry)
        modalities.sort(key=lambda m: (m["data_category"], m["data_type"]))
        result = {
            "project":      project,
            "cancer_type":  CANCER_TYPE,
            "n_modalities": len(modalities),
            "modalities":   modalities,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
        print(f"  [cache] saved {cache_path}", file=sys.stderr, flush=True)

    # Operator-imposed exclude list — applied BEFORE the cap so caps count
    # surviving modalities. Excluded modalities never become "expected", so
    # the coverage guard in write_summary won't demand them.
    notes: list[str] = []
    if TCGA_GDC_EXCLUDE:
        kept = []
        dropped = []
        for m in result.get("modalities", []) or []:
            if _is_excluded(m["data_category"], m["data_type"]):
                dropped.append(f"{m['data_category']}/{m['data_type']}")
            else:
                kept.append(m)
        result["modalities"] = kept
        result["excluded_modalities"] = dropped
        if dropped:
            notes.append(
                f"Operator-imposed exclude list (TCGA_GDC_EXCLUDE) dropped "
                f"{len(dropped)} modality(s): {', '.join(dropped)}. Do NOT "
                f"attempt to download them — they are not part of this run."
            )

    # Operator-imposed modality cap (skipped when master switch is on).
    if TCGA_GDC_MAX_MODALITIES is not None:
        total = len(result.get("modalities", []))
        if TCGA_GDC_MAX_MODALITIES < total:
            result["modalities"] = result["modalities"][:TCGA_GDC_MAX_MODALITIES]
            notes.append(
                f"Operator-imposed test cap (TCGA_GDC_MAX_MODALITIES="
                f"{TCGA_GDC_MAX_MODALITIES}). The {TCGA_GDC_MAX_MODALITIES} "
                f"modalities below are the COMPLETE work-list for this run "
                f"— profile every one of them and write the summary."
            )
    if notes:
        result["note"] = " ".join(notes)
    result["n_modalities"]   = len(result.get("modalities", []) or [])
    result["download_all_samples_mode"] = DOWNLOAD_ALL_SAMPLES
    EXPECTED_MODALITIES = result.get("modalities", []) or []
    return json.dumps(result, indent=2)


def list_files_for_modality(project: str, data_category: str, data_type: str) -> str:
    """Return file_ids for one modality. The tool makes the all-vs-cap
    decision and returns `recommended_file_ids` for the LLM to pass straight
    into `download_via_gdc_client`."""
    filters = {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": project}},
            {"op": "=", "content": {"field": "files.data_category",      "value": data_category}},
            {"op": "=", "content": {"field": "files.data_type",          "value": data_type}},
            {"op": "=", "content": {"field": "files.access",             "value": "open"}},
        ],
    }
    rows = _gdc_paginated_files(
        filters, fields="file_id,file_name,file_size,cases.case_id,cases.submitter_id"
    )
    total_files = len(rows)
    total_bytes = sum(int(r.get("file_size") or 0) for r in rows)

    by_case: dict[str, list[dict]] = {}
    for r in rows:
        for c in (r.get("cases") or []):
            cid = c.get("case_id")
            if cid:
                by_case.setdefault(cid, []).append(r)

    if DOWNLOAD_ALL_SAMPLES:
        decision = "all_master_switch"
        download_all = True
    elif TCGA_GDC_MAX_CASES is None:
        decision = "all_no_case_cap"
        download_all = True
    elif (total_bytes < TCGA_GDC_FULL_BYTES_THRESHOLD
          and total_files < TCGA_GDC_FULL_FILES_THRESHOLD):
        decision = (f"all_below_threshold "
                    f"(bytes<{TCGA_GDC_FULL_BYTES_THRESHOLD}, "
                    f"files<{TCGA_GDC_FULL_FILES_THRESHOLD})")
        download_all = True
    else:
        decision = f"capped_at_{TCGA_GDC_MAX_CASES}_cases"
        download_all = False

    if download_all:
        recommended_file_ids = [r["file_id"] for r in rows]
        n_cases_selected     = len(by_case)
    else:
        cases_sorted    = sorted(by_case.keys())
        selected_cases  = cases_sorted[:TCGA_GDC_MAX_CASES]
        seen: set[str]  = set()
        recommended_file_ids = []
        for cid in selected_cases:
            for r in by_case[cid]:
                fid = r["file_id"]
                if fid not in seen:
                    seen.add(fid)
                    recommended_file_ids.append(fid)
        n_cases_selected = len(selected_cases)

    return json.dumps({
        "project":              project,
        "data_category":        data_category,
        "data_type":            data_type,
        "total_files":          total_files,
        "total_bytes":          total_bytes,
        "n_cases_available":    len(by_case),
        "n_cases_selected":     n_cases_selected,
        "n_files_recommended":  len(recommended_file_ids),
        "decision":             decision,
        "recommended_file_ids": recommended_file_ids,
        "sample_file_names":    [r.get("file_name") for r in rows[:5]],
    }, indent=2)


def download_via_gdc_client(
    file_ids: list[str],
    data_category: str,
    data_type: str,
) -> str:
    """Write a manifest and run ./gdc-client (sibling file) to download the files."""
    if not file_ids:
        return json.dumps({"error": "no file_ids provided"})
    if not GDC_CLIENT_PATH.exists():
        return json.dumps({"error": f"gdc-client not found at {GDC_CLIENT_PATH}"})
    if not os.access(GDC_CLIENT_PATH, os.X_OK):
        return json.dumps({
            "error": f"gdc-client at {GDC_CLIENT_PATH} is not executable "
                     f"(chmod +x it once)"
        })

    type_dir = CANCER_TYPE_DIR / _sanitize(data_category) / _sanitize(data_type)
    type_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = type_dir / "_manifest.txt"
    lines = ["id\tfilename\tmd5\tsize\tstate"]
    lines.extend(f"{fid}\t\t\t\t" for fid in file_ids)
    manifest_path.write_text("\n".join(lines) + "\n")

    # Fetch + write per-file metadata (UUID -> patient barcode -> sample ->
    # aliquot -> workflow). Done before the download so the sidecar exists
    # even if gdc-client fails. Failures here are non-fatal.
    metadata_path = type_dir / "_metadata.tsv"
    n_metadata_rows = 0
    metadata_error: str | None = None
    try:
        print(f"  [metadata] fetching for {len(file_ids)} file(s)",
              file=sys.stderr, flush=True)
        hits = _fetch_file_metadata(file_ids)
        flat_rows = [_metadata_row_for_file(hit) for hit in hits]
        _write_metadata_tsv(flat_rows, metadata_path)
        n_metadata_rows = len(flat_rows)
        print(f"  [metadata] wrote {n_metadata_rows} row(s) to {metadata_path}",
              file=sys.stderr, flush=True)
    except Exception as e:
        metadata_error = f"{type(e).__name__}: {e}"
        print(f"  [metadata] FAILED: {metadata_error}",
              file=sys.stderr, flush=True)

    cmd = [
        str(GDC_CLIENT_PATH), "download",
        "-m", str(manifest_path),
        "-d", str(type_dir),
        "--retry-amount", "3",
        "--wait-time",    "5",
        "--no-related-files",
        "--no-annotations",
        "-n", "4",
    ]
    print(f"  [gdc-client] {' '.join(cmd)}", file=sys.stderr, flush=True)
    t0 = time.time()
    proc = subprocess.Popen(
        cmd, stdout=sys.stderr, stderr=sys.stderr, text=True, bufsize=1
    )
    proc.communicate()
    dt = time.time() - t0

    # gdc-client writes data files directly under <file_id>/ and puts its own
    # resume-state .parcel files under <file_id>/logs/. Only the former count
    # as "downloaded data".
    def _is_data_file(p: Path, root: Path) -> bool:
        if not p.is_file():
            return False
        if p.name.endswith(".partial") or p.name.endswith(".parcel"):
            return False
        if "logs" in p.relative_to(root).parts:
            return False
        return True

    downloaded: list[str] = []
    bytes_on_disk = 0
    missing: list[str] = []
    for fid in file_ids:
        subdir = type_dir / fid
        if not subdir.exists():
            missing.append(fid)
            continue
        real_files = [f for f in subdir.rglob("*") if _is_data_file(f, subdir)]
        if not real_files:
            missing.append(fid)
            continue
        for f in real_files:
            downloaded.append(str(f))
            bytes_on_disk += f.stat().st_size

    DOWNLOADED.add((data_category, data_type))
    return json.dumps({
        "data_category":               data_category,
        "data_type":                   data_type,
        "type_dir":                    str(type_dir),
        "manifest":                    str(manifest_path),
        "metadata_tsv":                str(metadata_path),
        "n_requested":                 len(file_ids),
        "n_downloaded_files_on_disk":  len(downloaded),
        "n_missing_file_ids":          len(missing),
        "n_metadata_rows":             n_metadata_rows,
        "metadata_error":              metadata_error,
        "bytes_on_disk":               bytes_on_disk,
        "duration_seconds":            round(dt, 1),
        "gdc_client_exit_code":        proc.returncode,
        "sample_paths":                downloaded[:5],
        "missing_file_ids_sample":     missing[:5],
    }, indent=2)


def list_files(directory: str, max_entries: int = 25) -> str:
    """Light-weight directory listing so the LLM can see what was downloaded."""
    p = Path(directory)
    if not p.exists():
        return json.dumps({"error": f"directory not found: {directory}"})
    entries = []
    for sub in sorted(p.rglob("*")):
        if sub.is_file():
            entries.append({"path": str(sub), "size_bytes": sub.stat().st_size})
        if len(entries) >= max_entries:
            break
    return json.dumps({
        "directory":     str(p),
        "n_files_shown": len(entries),
        "files":         entries,
    }, indent=2)


def list_pending_modalities() -> str:
    """Modalities not yet downloaded. Call before write_summary."""
    pending = [
        {"data_category": m["data_category"], "data_type": m["data_type"]}
        for m in EXPECTED_MODALITIES
        if (m["data_category"], m["data_type"]) not in DOWNLOADED
    ]
    return json.dumps({
        "n_expected":   len(EXPECTED_MODALITIES),
        "n_downloaded": len(DOWNLOADED),
        "n_pending":    len(pending),
        "pending":      pending,
    }, indent=2)


def write_summary(content: str) -> str:
    """Persist the agent's final markdown summary at
    <cancer_type_dir>/summary.md. Refuses if any modality is unfinished."""
    if not EXPECTED_MODALITIES:
        return json.dumps({
            "error": "no modalities enumerated yet — call list_gdc_data_types first"
        })
    pending = [
        {"data_category": m["data_category"], "data_type": m["data_type"]}
        for m in EXPECTED_MODALITIES
        if (m["data_category"], m["data_type"]) not in DOWNLOADED
    ]
    if pending:
        return json.dumps({
            "error": (f"refusing to write summary: {len(pending)} of "
                      f"{len(EXPECTED_MODALITIES)} modalities have not been "
                      f"downloaded. Call download_via_gdc_client for each."),
            "pending": pending,
        })
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(content)

    # Aggregate every per-modality _metadata.tsv under this cancer-type into
    # a single project-level metadata.tsv rollup. Skips files with mismatched
    # headers (defensive — schema changes would be obvious).
    rollup_path  = CANCER_TYPE_DIR / "metadata.tsv"
    rollup_rows  = 0
    rollup_parts: list[Path] = []
    rollup_error: str | None = None
    try:
        header_line = "\t".join(METADATA_COLUMNS) + "\n"
        with open(rollup_path, "w") as out:
            out.write(header_line)
            for tsv in sorted(CANCER_TYPE_DIR.rglob("_metadata.tsv")):
                with open(tsv) as inp:
                    first = inp.readline()
                    if first != header_line:
                        print(f"  [rollup] skip {tsv} (header mismatch)",
                              file=sys.stderr, flush=True)
                        continue
                    rollup_parts.append(tsv)
                    for line in inp:
                        out.write(line)
                        rollup_rows += 1
    except Exception as e:
        rollup_error = f"{type(e).__name__}: {e}"
        print(f"  [rollup] FAILED: {rollup_error}", file=sys.stderr, flush=True)

    return json.dumps({
        "written":              str(SUMMARY_PATH),
        "bytes":                SUMMARY_PATH.stat().st_size,
        "n_modalities_covered": len(EXPECTED_MODALITIES),
        "metadata_rollup":      str(rollup_path),
        "metadata_rollup_rows": rollup_rows,
        "metadata_parts_merged": len(rollup_parts),
        "metadata_rollup_error": rollup_error,
    })


TOOL_REGISTRY = {
    "list_gdc_data_types":      list_gdc_data_types,
    "list_files_for_modality":  list_files_for_modality,
    "download_via_gdc_client":  download_via_gdc_client,
    "list_files":               list_files,
    "list_pending_modalities":  list_pending_modalities,
    "write_summary":            write_summary,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_gdc_data_types",
            "description": (
                "Enumerate every open-access (data_category, data_type) "
                "modality available for the TCGA project on GDC. Returns "
                "JSON: {project, cancer_type, n_modalities, modalities:[...]}. "
                "Each modality entry has total_files, total_bytes, and "
                "n_cases_total across the full project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string",
                                "description": "TCGA project id, e.g. TCGA-LUAD"},
                },
                "required": ["project"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files_for_modality",
            "description": (
                "Query the GDC API for open-access files in one (data_category, "
                "data_type) and return `recommended_file_ids` — either all "
                "files (when the modality is small or the master switch is on) "
                "or the files for the first N distinct cases (test mode). "
                "Pass `recommended_file_ids` straight into download_via_gdc_client."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project":       {"type": "string"},
                    "data_category": {"type": "string"},
                    "data_type":     {"type": "string"},
                },
                "required": ["project", "data_category", "data_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_via_gdc_client",
            "description": (
                "Write a manifest, fetch a per-file metadata sidecar "
                "(_metadata.tsv: one row per file with file_uuid, file_name, "
                "project, data_category/type/format, workflow_type, file_size, "
                "md5sum, access, patient_id (12-char TCGA barcode), "
                "sample_barcode, aliquot_barcode, sample_type, plus UUID "
                "variants — multi-valued cells are semicolon-joined), and "
                "invoke ./gdc-client (sibling file) to download every file in `file_ids` "
                "into <cancer_type>/<data_category>/<data_type>/<file_id>/"
                "<file>. Returns paths, bytes on disk, gdc-client exit code, "
                "and the metadata sidecar path + row count. Pass the "
                "`recommended_file_ids` returned by list_files_for_modality."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "GDC file UUIDs to download.",
                    },
                    "data_category": {"type": "string"},
                    "data_type":     {"type": "string"},
                },
                "required": ["file_ids", "data_category", "data_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List up to max_entries files under a directory (recursive).",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory":   {"type": "string"},
                    "max_entries": {"type": "integer", "default": 25},
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_modalities",
            "description": (
                "Return modalities from list_gdc_data_types that have not yet "
                "been downloaded. Call between batches and always right before "
                "write_summary. write_summary refuses while this is non-empty."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_summary",
            "description": (
                "Persist the final markdown summary covering every modality "
                "downloaded (file counts, bytes on disk, cases covered, "
                "decision rationale, gdc-client exit codes). Writes to "
                "<cancer_type>/summary.md. Also concatenates every per-"
                "modality _metadata.tsv into a project-level "
                "<cancer_type>/metadata.tsv rollup automatically. Refuses if "
                "any modality is missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Full markdown body."},
                },
                "required": ["content"],
            },
        },
    },
]


def call_tool(name: str, arguments: str) -> str:
    try:
        kwargs = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"bad JSON arguments: {e}"})
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool '{name}'"})
    try:
        return fn(**kwargs)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""\
You are a TCGA data-repository profiling agent that uses the GDC Data
Transfer Tool (gdc-client) to download open-access files for a project,
organised by cancer type.

Workflow:
  1. Call `list_gdc_data_types` once. The returned `modalities` array IS
     your complete work-list (already filtered to open-access; may be
     operator-capped for testing — either way, treat exactly the items it
     returns as the full set you must profile).
  2. For EACH modality, call `list_files_for_modality` to get
     `recommended_file_ids`. Do NOT second-guess the sampling decision —
     the tool already factored in the master switch and size thresholds.
  3. Pass `recommended_file_ids` straight into `download_via_gdc_client`
     with the same `data_category` and `data_type`. Check the response
     for `gdc_client_exit_code` and `n_missing_file_ids` — if non-zero
     missing, note it (gdc-client occasionally fails on individual files;
     do not retry the whole modality unless the exit code is non-zero).
  4. After every modality has been downloaded, call
     `list_pending_modalities`. If anything is pending, finish those
     downloads and re-check until pending is zero.
  5. Only then call `write_summary` exactly once. The markdown should be
     organised as:
        # TCGA {{project}} — gdc-client extraction summary
        ## <Data Category>
        ### <Data Type>
        - total_files / total_bytes (full project)
        - cases requested / files requested
        - files actually on disk / bytes on disk
        - gdc-client exit code, any missing file ids
        - decision rationale (capped / full / threshold)
        - metadata sidecar: <_metadata.tsv path>, n_metadata_rows
     Group modalities by category. Flag any modality where the exit code
     was non-zero, files are missing, or metadata_error is non-null. End
     the markdown with a brief section noting that a project-level
     metadata.tsv is also written automatically at the cancer-type root.
  6. Return a brief plain-text confirmation that the summary was written
     and mention both the summary path and the metadata rollup path
     (returned in write_summary's response as `metadata_rollup`).

Rules:
  - Open-access only. Controlled-access modalities are filtered at the API.
  - You MUST profile every modality returned by step 1. The system blocks
    summary writes until all are covered.
  - Issue tool calls sequentially; downloads can take a while.
  - Never invent file ids or file names — only report what the tools return.
"""

USER_PROMPT = (
    f"Profile every publicly available data modality for {TCGA_PROJECT}. "
    f"Download into {CANCER_TYPE_DIR} and write the summary to {SUMMARY_PATH}."
)


def run_agent() -> None:
    print(f"=== TCGA gdc-client agent ===", flush=True)
    print(f"  model              : {ARGO_MODEL}", flush=True)
    print(f"  project            : {TCGA_PROJECT}", flush=True)
    print(f"  cancer type        : {CANCER_TYPE}", flush=True)
    print(f"  output root        : {TCGA_GDC_OUTPUT_ROOT}", flush=True)
    print(f"  cancer-type dir    : {CANCER_TYPE_DIR}", flush=True)
    print(f"  summary path       : {SUMMARY_PATH}", flush=True)
    print(f"  gdc-client         : {GDC_CLIENT_PATH}", flush=True)
    print(f"  DOWNLOAD_ALL_SAMPLES: {DOWNLOAD_ALL_SAMPLES}", flush=True)
    print(f"  max cases/modality : "
          f"{TCGA_GDC_MAX_CASES if TCGA_GDC_MAX_CASES is not None else 'unlimited'}",
          flush=True)
    if TCGA_GDC_MAX_MODALITIES is not None:
        print(f"  max modalities     : {TCGA_GDC_MAX_MODALITIES}", flush=True)
    if TCGA_GDC_EXCLUDE:
        readable = [(f"{c}/{t}" if c else t) for c, t in TCGA_GDC_EXCLUDE]
        print(f"  excluding          : {', '.join(readable)}", flush=True)
    print(f"  full-modality thresholds: "
          f"<{TCGA_GDC_FULL_BYTES_THRESHOLD} bytes AND "
          f"<{TCGA_GDC_FULL_FILES_THRESHOLD} files", flush=True)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_PROMPT},
    ]

    turn = 0
    while True:
        turn += 1
        print(f"\n--- turn {turn} ---", flush=True)
        resp = client.chat.completions.create(
            model=ARGO_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        if msg.content:
            print(f"[assistant] {msg.content}", flush=True)
        if not msg.tool_calls:
            print(f"\n=== done after {turn} turns ===", flush=True)
            return
        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            print(f"[tool-call] {name}({args[:200]}{'...' if len(args) > 200 else ''})",
                  flush=True)
            result  = call_tool(name, args)
            preview = result[:300].replace("\n", " ")
            print(f"[tool-result] {preview}{'...' if len(result) > 300 else ''}",
                  flush=True)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })


if __name__ == "__main__":
    run_agent()
