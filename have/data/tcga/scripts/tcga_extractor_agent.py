"""
TCGA data-repository extractor agent.

Goal: enumerate every publicly available data modality for a TCGA project
(default TCGA-LUAD), download all open-access files, extract a schema
(column heads + dtypes) per modality, and emit a consolidated markdown
summary at  data/tcga/<PROJECT>/schema_summary.md.

Architecture:
  - Hand-rolled OpenAI-tool-calling loop against the Argo Gateway (gpt54).
  - Tools are Python functions that shell out to tcga_helpers.R (sibling file) via
    the conda env's Rscript. R does the heavy lifting (TCGAbiolinks).

Output layout (matches TCGAbiolinks' native structure):
  <TCGA_OUTPUT_ROOT>/<PROJECT>/<data_category>/<data_type>/<file_id>/<file>
  <TCGA_OUTPUT_ROOT>/<PROJECT>/<data_category>/<data_type>/prepared.rds
  <TCGA_OUTPUT_ROOT>/<PROJECT>/schema_summary.md

Run:
    conda run -n biomni_e1 python have/data/tcga/scripts/tcga_extractor_agent.py
Env vars (all optional):
    ARGO_USER          ANL domain username (default: yitan.zhu)
    ARGO_MODEL         Argo model name     (default: gpt54)
    TCGA_PROJECT       TCGA project id     (default: TCGA-LUAD)
    TCGA_OUTPUT_ROOT   output dir          (default: have/data/tcga/data)
    TCGA_MAX_FILES     per-modality file cap     (default: 5 — feasibility
                                                  test mode; set to 0 or
                                                  "unlimited" to download
                                                  every file)
    TCGA_MAX_MODALITIES per-project modality cap (default: unlimited; useful
                                                  for fast end-to-end tests)
    TCGA_EXCLUDE_DATA_TYPES  comma-separated data_type names to skip
                             (default: "Slide Image" — SVS is ~500 MB each.
                              Set to "" to include everything, or e.g.
                              "Slide Image,Masked Intensities" to also skip
                              the methylation IDATs.)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER     = os.environ.get("ARGO_USER",  "yitan.zhu")
ARGO_MODEL    = os.environ.get("ARGO_MODEL", "gpt54")

TCGA_PROJECT     = os.environ.get("TCGA_PROJECT", "TCGA-LUAD")
SCRIPT_DIR       = Path(__file__).resolve().parent
DEFAULT_ROOT     = SCRIPT_DIR.parent / "data"   # have/data/tcga/data/
TCGA_OUTPUT_ROOT = Path(os.environ.get("TCGA_OUTPUT_ROOT", str(DEFAULT_ROOT))).resolve()

# Feasibility-test default: cap each modality to 5 files. Set to "0" or
# "unlimited" (any non-numeric) to download every file in a modality.
def _parse_max_files(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return 5                       # feasibility-test default
    try:
        n = int(raw)
    except ValueError:
        return None                    # "unlimited", "all", etc.
    return None if n <= 0 else n

TCGA_MAX_FILES      = _parse_max_files(os.environ.get("TCGA_MAX_FILES"))
TCGA_MAX_MODALITIES = os.environ.get("TCGA_MAX_MODALITIES")    # str or None

# Comma-separated data_type names to skip (matched case-insensitively, exact).
# Default skips Slide Image because SVS is ~500 MB × thousands of files —
# usually you don't want it in a feasibility run. Set TCGA_EXCLUDE_DATA_TYPES=""
# to include everything, or e.g. "Slide Image,Masked Intensities" to also skip
# the methylation IDAT files.
_DEFAULT_EXCLUDED = "Slide Image"
TCGA_EXCLUDE_DATA_TYPES = {
    s.strip().lower()
    for s in os.environ.get("TCGA_EXCLUDE_DATA_TYPES", _DEFAULT_EXCLUDED).split(",")
    if s.strip()
}

R_HELPER_PATH = SCRIPT_DIR / "tcga_helpers.R"
RSCRIPT_PATH  = Path(sys.prefix) / "bin" / "Rscript"   # conda env's Rscript

# TCGAbiolinks' GDCdownload writes to <directory>/<project>/<cat>/<type>/...
# We give it TCGA_OUTPUT_ROOT directly so the natural project folder is the
# top-level grouping (e.g. have/data/tcga/data/TCGA-LUAD/...). No extra cancer
# subfolder layer.
TCGA_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
PROJECT_DIR  = TCGA_OUTPUT_ROOT / TCGA_PROJECT
SUMMARY_PATH = PROJECT_DIR / "schema_summary.md"

client = OpenAI(base_url=ARGO_BASE_URL, api_key=ARGO_USER)


# ---------------------------------------------------------------------------
# Coverage tracking — guarantees every modality is downloaded AND schema-
# extracted before the agent is allowed to write the final summary. Without
# this, an LLM running a 21-modality x 2-tool-calls loop will sometimes
# truncate early and write a partial summary.
# ---------------------------------------------------------------------------
def _sanitize(x: str | None) -> str:
    """Mirror of R's sanitize(): collapses non-[A-Za-z0-9._-] runs into '_'."""
    if x is None or x == "":
        return "default"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", x)

def _modality_key(category: str, dtype: str, workflow: str | None) -> tuple:
    return (category, dtype, workflow or None)

# Filled by list_tcga_public_data_types (post-cap):
EXPECTED_MODALITIES: list[dict] = []
DOWNLOADED:        set[tuple] = set()
SCHEMA_EXTRACTED:  set[tuple] = set()

def _modality_type_dir(modality: dict) -> Path:
    return (PROJECT_DIR
            / _sanitize(modality["data_category"])
            / _sanitize(modality["data_type"]))

def _coverage_pending() -> list[dict]:
    out = []
    for m in EXPECTED_MODALITIES:
        key = _modality_key(m["data_category"], m["data_type"], m.get("workflow_type"))
        dl  = key in DOWNLOADED
        sx  = key in SCHEMA_EXTRACTED
        if dl and sx:
            continue
        out.append({
            "data_category": m["data_category"],
            "data_type":     m["data_type"],
            "workflow_type": m.get("workflow_type"),
            "downloaded":        dl,
            "schema_extracted":  sx,
        })
    return out


# ---------------------------------------------------------------------------
# R bridge
# ---------------------------------------------------------------------------
def _run_r(action: str, params: dict) -> dict:
    """Call tcga_helpers.R (sibling file) with {action, params}; return parsed JSON.

    R writes its JSON response to a temp file (response_path in the request)
    rather than stdout — TCGAbiolinks' GDCdownload prints a progress bar
    straight to stdout that would otherwise corrupt JSON capture. R's stdout
    and stderr (the progress chatter) are forwarded live to our stderr so the
    user sees progress in real time.
    """
    print(f"  [R] action={action} params={params}", file=sys.stderr, flush=True)
    t0 = time.time()
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as fp:
        response_path = fp.name
    try:
        payload = json.dumps({"action": action, "params": params,
                              "response_path": response_path})
        proc = subprocess.Popen(
            [str(RSCRIPT_PATH), str(R_HELPER_PATH)],
            stdin=subprocess.PIPE,
            stdout=sys.stderr,           # let TCGAbiolinks chatter pass through
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        proc.communicate(input=payload)
        dt = time.time() - t0
        if proc.returncode != 0:
            raise RuntimeError(
                f"R helper failed (action={action}, exit={proc.returncode}, {dt:.1f}s)"
            )
        with open(response_path) as f:
            response_text = f.read()
        if not response_text.strip():
            raise RuntimeError(
                f"R helper wrote no response (action={action}, {dt:.1f}s)"
            )
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"R helper wrote non-JSON response (action={action}):\n"
                f"{response_text[:2000]}\n--- error: {e}"
            )
    finally:
        try: os.unlink(response_path)
        except OSError: pass


# ---------------------------------------------------------------------------
# Tool implementations (called from the agent loop)
# ---------------------------------------------------------------------------
def list_tcga_public_data_types(project: str) -> str:
    """Enumerate every open-access (category, type, workflow) combo."""
    global EXPECTED_MODALITIES
    # The R listing query takes 15-20 min (one GDCquery per category).
    # Cache it per-project so re-runs / smoke tests are fast. Bypass with
    # TCGA_FORCE_RELIST=1.
    cache_path = TCGA_OUTPUT_ROOT / project / "modalities_cache.json"
    if cache_path.exists() and not os.environ.get("TCGA_FORCE_RELIST"):
        print(f"  [cache] using {cache_path}", file=sys.stderr, flush=True)
        result = json.loads(cache_path.read_text())
    else:
        result = _run_r("list_public_data_types", {"project": project})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, indent=2))
        print(f"  [cache] saved {cache_path}", file=sys.stderr, flush=True)
    # Operator-imposed exclusion of specific data_types (e.g. Slide Image is
    # huge SVS files). Applied BEFORE the modality cap so the cap counts only
    # the work the agent is actually going to do. Cache stays unfiltered so
    # toggling the exclusion list doesn't require a re-discovery.
    if TCGA_EXCLUDE_DATA_TYPES and result.get("modalities"):
        before = len(result["modalities"])
        kept, dropped = [], []
        for m in result["modalities"]:
            if (m.get("data_type") or "").strip().lower() in TCGA_EXCLUDE_DATA_TYPES:
                dropped.append(f"{m.get('data_category')} / {m.get('data_type')}")
            else:
                kept.append(m)
        result["modalities"] = kept
        if dropped:
            print(f"  [exclude] skipping {len(dropped)}/{before} modality entries "
                  f"by data_type: {dropped}", file=sys.stderr, flush=True)
            result["excluded_data_types"] = sorted(TCGA_EXCLUDE_DATA_TYPES)
            result["excluded_entries"]    = dropped

    if TCGA_MAX_MODALITIES and result.get("modalities"):
        cap = int(TCGA_MAX_MODALITIES)
        total = len(result["modalities"])
        if cap < total:
            result["modalities"] = result["modalities"][:cap]
            # Don't expose a "capped" flag that scares the agent off — present
            # the truncated list as the canonical work-list and explain why.
            result["note"] = (
                f"Operator-imposed test cap (TCGA_MAX_MODALITIES={cap}). "
                f"The {cap} modalities below are the COMPLETE work-list for "
                f"this run — profile every one of them and write the summary. "
                f"This is normal feasibility-test behaviour."
            )
    # Always reflect the post-cap count so the agent treats `modalities` as
    # the source of truth.
    result["n_modalities"] = len(result.get("modalities", []) or [])
    EXPECTED_MODALITIES = result.get("modalities", []) or []
    return json.dumps(result, indent=2)


def download_tcga_modality(
    project: str,
    data_category: str,
    data_type: str,
    workflow_type: str | None = None,
) -> str:
    """Download one open-access modality into the cancer-type tree."""
    params = {
        "project":       project,
        "data_category": data_category,
        "data_type":     data_type,
        "workflow_type": workflow_type,
        "output_root":   str(TCGA_OUTPUT_ROOT),
    }
    if TCGA_MAX_FILES is not None:
        params["max_files"] = TCGA_MAX_FILES
    result = _run_r("download_modality", params)
    DOWNLOADED.add(_modality_key(data_category, data_type, workflow_type))
    return json.dumps(result, indent=2)


def extract_schema(file_path: str) -> str:
    """Describe the columns / structure of a downloaded file."""
    result = _run_r("extract_schema", {"file_path": file_path})
    # Mark every modality whose type_dir is an ancestor of file_path as
    # schema-extracted. Path-based matching avoids needing the LLM to pass
    # a modality id explicitly.
    try:
        resolved = Path(file_path).resolve()
        for m in EXPECTED_MODALITIES:
            type_dir = _modality_type_dir(m).resolve()
            try:
                resolved.relative_to(type_dir)
            except ValueError:
                continue
            SCHEMA_EXTRACTED.add(
                _modality_key(m["data_category"], m["data_type"],
                              m.get("workflow_type"))
            )
    except Exception:
        pass     # never fail the tool because tracking went wrong
    return json.dumps(result, indent=2)


def list_pending_modalities() -> str:
    """Modalities not yet fully profiled (download + schema). Call before
    `write_schema_summary` to make sure nothing was missed."""
    pending = _coverage_pending()
    return json.dumps({
        "n_expected": len(EXPECTED_MODALITIES),
        "n_downloaded": len(DOWNLOADED),
        "n_schema_extracted": len(SCHEMA_EXTRACTED),
        "n_pending": len(pending),
        "pending": pending,
    }, indent=2)


def list_files(directory: str, max_entries: int = 25) -> str:
    """Light-weight directory listing so the LLM can see what was downloaded."""
    p = Path(directory)
    if not p.exists():
        return json.dumps({"error": f"directory not found: {directory}"})
    entries = []
    for sub in sorted(p.rglob("*")):
        if sub.is_file():
            entries.append({
                "path": str(sub),
                "size_bytes": sub.stat().st_size,
            })
        if len(entries) >= max_entries:
            break
    return json.dumps({
        "directory": str(p),
        "n_files_shown": len(entries),
        "files": entries,
    }, indent=2)


def write_schema_summary(content: str) -> str:
    """Persist the agent's final consolidated markdown summary."""
    # Refuse if list_tcga_public_data_types was never called or any modality
    # is unprofiled — protects against partial summaries.
    if not EXPECTED_MODALITIES:
        return json.dumps({
            "error": "no modalities enumerated yet — call "
                     "list_tcga_public_data_types first"
        })
    pending = _coverage_pending()
    if pending:
        return json.dumps({
            "error": (f"refusing to write summary: {len(pending)} of "
                      f"{len(EXPECTED_MODALITIES)} modalities are not yet "
                      f"profiled. Call download_tcga_modality and/or "
                      f"extract_schema for each pending modality below, then "
                      f"call write_schema_summary again."),
            "pending": pending,
        })
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(content)
    return json.dumps({"written": str(SUMMARY_PATH),
                       "bytes": SUMMARY_PATH.stat().st_size,
                       "n_modalities_covered": len(EXPECTED_MODALITIES)})


TOOL_REGISTRY = {
    "list_tcga_public_data_types": list_tcga_public_data_types,
    "download_tcga_modality":      download_tcga_modality,
    "extract_schema":              extract_schema,
    "list_files":                  list_files,
    "list_pending_modalities":     list_pending_modalities,
    "write_schema_summary":        write_schema_summary,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tcga_public_data_types",
            "description": (
                "Enumerate every open-access (data_category, data_type, "
                "workflow_type) modality available for a TCGA project on GDC. "
                "Returns JSON: {project, n_modalities, modalities:[...]}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string",
                                "description": "TCGA project id, e.g. TCGA-LUAD"}
                },
                "required": ["project"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_tcga_modality",
            "description": (
                "Download all open-access files for one (data_category, "
                "data_type, workflow_type) combo via TCGAbiolinks "
                "(GDCquery + GDCdownload + GDCprepare). Saves raw files under "
                "<project>/<category>/<type>/<file_id>/<file> and a "
                "prepared.rds (or <workflow>.prepared.rds when multiple "
                "workflows share a type) at the type directory. Returns "
                "paths and basic counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project":       {"type": "string"},
                    "data_category": {"type": "string"},
                    "data_type":     {"type": "string"},
                    "workflow_type": {
                        "type": ["string", "null"],
                        "description": "Pass null if the modality has no workflow_type."
                    },
                },
                "required": ["project", "data_category", "data_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_schema",
            "description": (
                "Describe the schema (column names, dtypes, example values) of "
                "a single downloaded file. Handles .rds (SummarizedExperiment "
                "/ data.frame / list), tabular files (.tsv/.csv/.maf, with or "
                "without .gz), and .xml. Prefer the modality's prepared.rds "
                "(richer metadata) over individual raw files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string",
                                  "description": "Absolute path to one file."}
                },
                "required": ["file_path"],
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
                "Return modalities from list_tcga_public_data_types that have "
                "not yet been both downloaded AND schema-extracted. Call this "
                "between batches and ALWAYS right before write_schema_summary "
                "to make sure nothing was skipped. write_schema_summary will "
                "refuse to run while this list is non-empty."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_schema_summary",
            "description": (
                "Persist the final markdown summary covering every modality "
                "examined (column names per modality, n_features, n_samples, "
                "file format, notable fields, controlled-access exclusions, "
                "etc.). Writes to data/tcga/<PROJECT>/schema_summary.md."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string",
                                "description": "Full markdown body."}
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
    except Exception as e:           # surface to the LLM so it can recover
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""\
You are a data-repository profiling agent. Your job is to enumerate, download,
and document every publicly available data modality for a given TCGA project,
then write a consolidated schema summary to disk.

Workflow:
  1. Call `list_tcga_public_data_types` once. The returned `modalities`
     array IS your complete work-list (it has already been filtered to
     open-access types and may have been capped for testing — either way,
     treat exactly the items it returns as the full set you must profile).
  2. For EACH modality returned, call `download_tcga_modality`. Use the exact
     values returned in step 1 (pass null for workflow_type if it was null).
     The tool returns paths including `prepared_path` (the GDCprepare-parsed
     .rds) and `sample_raw_files`.
  3. For EACH modality, call `extract_schema` on `prepared_path` when it is
     non-null; otherwise on one representative raw file from
     `sample_raw_files`. (You can call `list_files` on `type_dir` if you need
     to find another file to schema.) `prepared_path` being null is normal
     for binary modalities like Slide Image (SVS) — don't retry, just fall
     back to a raw file.
  4. After every modality has been BOTH downloaded and schema-extracted,
     call `list_pending_modalities`. If it returns any pending entries,
     finish them first (download + extract_schema for each one) and call
     `list_pending_modalities` again until it reports zero pending.
  5. Only then call `write_schema_summary` exactly once. It will refuse with
     a `pending` list if any modality is missing — treat that as a directive
     to finish those before retrying. The markdown should be organised as:
        # TCGA {{project}} – schema summary
        ## <Data Category>
        ### <Data Type>  (workflow: <workflow_type or n/a>)
        - n_files, prepared object class, n_features, n_samples
        - colData columns: name (dtype) – example values
        - rowData / tabular columns: same
     Group modalities by category. Note any modalities that failed to download
     or prepare, including the error.
  6. Return a brief plain-text confirmation that the summary was written.

Rules:
  - Controlled-access categories (Sequencing Reads, Structural Variation,
    Somatic Structural Variation) will not appear in step 1's results
    (they are filtered out). Do not try to download them.
  - You MUST profile every modality returned by step 1. Do not stop early
    based on "looks like enough" — the system will block summary writes
    until all are covered.
  - Never invent column names — only report what `extract_schema` returns.
  - Tool calls may take a long time (downloads run to completion). Issue them
    sequentially; do not batch many in parallel.
  - If a `download_tcga_modality` call returns a non-empty `prepare_error`
    AND `prepared_path` is null AND `sample_raw_files` is empty, log the
    failure in the summary and move on. Otherwise always run extract_schema.
"""

USER_PROMPT = (
    f"Profile every publicly available data modality for {TCGA_PROJECT}. "
    f"Download into {PROJECT_DIR} and write the consolidated schema summary "
    f"to {SUMMARY_PATH}."
)


def run_agent() -> None:
    print(f"=== TCGA extractor agent ===", flush=True)
    print(f"  model        : {ARGO_MODEL}", flush=True)
    print(f"  project      : {TCGA_PROJECT}", flush=True)
    print(f"  output root  : {TCGA_OUTPUT_ROOT}", flush=True)
    print(f"  project dir  : {PROJECT_DIR}", flush=True)
    print(f"  summary path : {SUMMARY_PATH}", flush=True)
    files_label = TCGA_MAX_FILES if TCGA_MAX_FILES is not None else "unlimited"
    print(f"  max files/modality: {files_label}", flush=True)
    if TCGA_MAX_MODALITIES:
        print(f"  max modalities    : {TCGA_MAX_MODALITIES}", flush=True)
    if TCGA_EXCLUDE_DATA_TYPES:
        print(f"  excluded types    : {sorted(TCGA_EXCLUDE_DATA_TYPES)}", flush=True)

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
            result = call_tool(name, args)
            preview = result[:300].replace("\n", " ")
            print(f"[tool-result] {preview}{'...' if len(result) > 300 else ''}",
                  flush=True)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })


def _write_project_rollups() -> None:
    """Concatenate per-modality manifest.tsv files into project-level rollups.

    Produces:
      <PROJECT_DIR>/file_manifest.tsv  — every file across modalities, one row per file
      <PROJECT_DIR>/patient_files.tsv  — patient_id rows × modality columns, cells = file_id(s)
    """
    # Two naming conventions live side-by-side: `manifest.tsv` (no workflow)
    # and `<workflow>.manifest.tsv`. A bare `*.manifest.tsv` glob misses the
    # former — collect both explicitly via rglob, then de-duplicate.
    manifest_files = sorted({
        *PROJECT_DIR.rglob("manifest.tsv"),
        *PROJECT_DIR.rglob("*.manifest.tsv"),
    })
    if not manifest_files:
        print("  [rollup] no manifest.tsv files found — skipping rollup", flush=True)
        return
    try:
        import pandas as pd
    except ImportError:
        print("  [rollup] pandas not available — skipping rollup", flush=True)
        return

    frames = []
    for mf in manifest_files:
        try:
            df = pd.read_csv(mf, sep="\t", dtype=str, keep_default_na=False)
        except Exception as e:
            print(f"  [rollup] failed to read {mf}: {e}", flush=True)
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        print("  [rollup] all manifests empty — skipping rollup", flush=True)
        return

    combined = pd.concat(frames, ignore_index=True)
    file_manifest_path = PROJECT_DIR / "file_manifest.tsv"
    combined.to_csv(file_manifest_path, sep="\t", index=False)
    print(f"  [rollup] wrote {file_manifest_path} ({len(combined)} rows)", flush=True)

    with_patient = combined[combined["patient_id"].astype(str).str.len() > 0]
    if with_patient.empty:
        print("  [rollup] no rows with patient_id — skipping patient_files.tsv",
              flush=True)
        return
    wt = with_patient["workflow_type"].fillna("").replace("", "n/a")
    modality = (with_patient["data_category"].astype(str) + " / " +
                with_patient["data_type"].astype(str) + " / " + wt)
    with_patient = with_patient.assign(_modality=modality)
    pivot = (with_patient.groupby(["patient_id", "_modality"])["file_id"]
             .apply(lambda s: ",".join(sorted(set(s.dropna().astype(str)))))
             .unstack(fill_value=""))
    patient_files_path = PROJECT_DIR / "patient_files.tsv"
    pivot.to_csv(patient_files_path, sep="\t")
    print(f"  [rollup] wrote {patient_files_path} "
          f"({pivot.shape[0]} patients × {pivot.shape[1]} modalities)", flush=True)


def _fmt_bytes(b: float | None) -> str:
    if b is None or b != b:    # None or NaN
        return "?"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while b >= 1024 and i < len(units) - 1:
        b /= 1024
        i += 1
    return f"{b:.1f} {units[i]}"


# What each TCGA data_type contains, in plain prose. Keyed by data_type.
# Workflow column in the table already tells the user which pipeline produced
# the file; descriptions deliberately don't repeat the workflow name.
_DATA_TYPE_DESCRIPTIONS: dict[str, str] = {
    "Slide Image":
        "Whole-slide histopathology images (SVS, Aperio format). Multiple "
        "slides per patient (diagnostic + frozen tissue).",
    "Masked Intensities":
        "Raw methylation array intensities (IDAT). 2 files per array "
        "(Grn + Red channels); some patients have both 450k + EPIC arrays.",
    "Methylation Beta Value":
        "Per-CpG β-values (TXT) derived from IDAT. ~450k–850k probes per file.",
    "Gene Expression Quantification":
        "RNA-seq gene counts from STAR. ~60k Ensembl genes × {unstranded, "
        "stranded fwd/rev, TPM, FPKM, FPKM-uq}.",
    "Gene Level Copy Number":
        "Per-gene CN integer calls (~60k genes per sample).",
    "Copy Number Segment":
        "Genomic segments with CN call (chr/start/end/n_probes/mean_log2).",
    "Masked Copy Number Segment":
        "Copy Number Segment with germline-CNV regions masked out.",
    "Allele-specific Copy Number Segment":
        "Per-segment major/minor allele copy numbers.",
    "Masked Somatic Mutation":
        "MAF format: somatic variant calls masked for germline. Hundreds to "
        "thousands of mutations per tumor.",
    "Annotated Somatic Mutation":
        "Per-caller somatic variants with functional annotation (VEP).",
    "Aggregated Somatic Mutation":
        "Project-level aggregated somatic variant calls.",
    "Raw Simple Somatic Mutation":
        "Per-caller raw somatic SNVs/indels before consensus masking.",
    "Isoform Expression Quantification":
        "Per-isoform miRNA read counts (mature + star isoforms).",
    "miRNA Expression Quantification":
        "Mature-miRNA-level read counts (~2k miRNAs per sample).",
    "Splice Junction Quantification":
        "STAR splice-junction read counts per sample.",
    "Single Cell Analysis":
        "Per-sample single-cell expression matrices.",
    "Pathology Report":
        "Scanned pathology PDFs (free text + figures); one per patient.",
    "Clinical Supplement":
        "Patient clinical metadata (XML + Biotab): demographics, stage, "
        "treatment, follow-up, vitals.",
    "Biospecimen Supplement":
        "Sample/aliquot/portion/slide metadata (XML + Biotab); multiple per "
        "patient (one per sample/aliquot).",
    "Protein Expression Quantification":
        "RPPA (reverse-phase protein array): ~200 antibodies × samples.",
}


def _describe_modality(data_type: str) -> str:
    return _DATA_TYPE_DESCRIPTIONS.get(data_type, f"TCGA {data_type} data.")


def _write_size_summary() -> None:
    """Per-project data-modality size ranking, saved to <PROJECT_DIR>/size_summary.md.

    Uses the listing cache for total file counts + case_count, and the project
    rollup (file_manifest.tsv) for measured mean file sizes from the downloaded
    samples. Per-patient estimate = mean_file_size × (n_files_total / case_count).
    """
    cache_path = PROJECT_DIR / "modalities_cache.json"
    manifest_path = PROJECT_DIR / "file_manifest.tsv"
    if not cache_path.exists():
        print(f"  [size-summary] {cache_path} missing — skipping", flush=True)
        return
    try:
        import pandas as pd
    except ImportError:
        print("  [size-summary] pandas not available — skipping", flush=True)
        return

    cache = json.loads(cache_path.read_text())
    modalities = cache.get("modalities") or []
    if not modalities:
        print("  [size-summary] cache has no modalities — skipping", flush=True)
        return

    # case_count: prefer R's value; fall back to max files-per-modality across
    # modalities where files-per-patient is ~1 (a rough proxy).
    case_count = cache.get("case_count")
    if not case_count:
        # Filter to modalities with workflows that typically have 1 file/patient
        # (Clinical/Pathology/Gene Expression). Take max as proxy.
        proxy_n = [
            m["n_files"] for m in modalities
            if (m.get("data_type") or "").lower() in
               {"clinical supplement", "pathology report",
                "gene expression quantification", "masked somatic mutation"}
        ]
        case_count = max(proxy_n) if proxy_n else None

    # Per-modality measurements from the manifest:
    #   - mean file size (bytes) across files we actually downloaded
    #   - n_sampled (how many files were measured — informational)
    #   - n_patients with data in this modality (unique patient_id count)
    # When TCGA_MAX_FILES=0 the manifest holds every file and these numbers
    # are exact. When capped (default 5), they reflect only the sampled slice.
    mean_sizes:    dict[tuple, tuple[float, int]] = {}
    patient_counts: dict[tuple, int]              = {}
    if manifest_path.exists():
        try:
            mf = pd.read_csv(manifest_path, sep="\t", dtype=str, keep_default_na=False)
            mf["file_size_n"] = pd.to_numeric(mf["file_size"], errors="coerce")
            mf["wf_norm"] = mf["workflow_type"].replace("", "n/a")
            for (cat, dt, wf), grp in mf.groupby(["data_category", "data_type", "wf_norm"]):
                key = (cat, dt, wf)
                mean_sizes[key] = (float(grp["file_size_n"].mean()), int(len(grp)))
                pids = grp["patient_id"].astype(str)
                patient_counts[key] = int(pids[pids.str.len() > 0].nunique())
        except Exception as e:
            print(f"  [size-summary] failed to read {manifest_path}: {e}", flush=True)

    rows = []
    for m in modalities:
        cat = m["data_category"]
        dt  = m["data_type"]
        wf  = m.get("workflow_type") or "n/a"
        n_files = m.get("n_files", 0)
        mean_size, sampled = mean_sizes.get((cat, dt, wf), (None, 0))
        total = (mean_size * n_files) if mean_size is not None else None
        rows.append({
            "category": cat, "data_type": dt, "workflow": wf,
            "n_files_total":   n_files,
            "mean_file_bytes": mean_size,
            "sampled":         sampled,
            "total_bytes":     total,
            "n_patients":      patient_counts.get((cat, dt, wf), 0),
        })

    # Sort by total project size desc; modalities with no sample (None size)
    # bubble to top so the user notices them.
    rows.sort(key=lambda r: (r["total_bytes"] is None, -(r["total_bytes"] or 0)))

    project = cache.get("project", TCGA_PROJECT)
    out = []
    out.append(f"# {project} — data modalities by size\n")
    case_count_note = ("from getProjectSummary" if cache.get("case_count")
                       else "proxy from max single-file modality")
    out.append(f"- Project case count: **{case_count if case_count else '?'}** "
               f"({case_count_note})")
    out.append(f"- Modalities profiled: {len(modalities)}")
    if TCGA_EXCLUDE_DATA_TYPES:
        out.append(f"- Excluded data_types: {sorted(TCGA_EXCLUDE_DATA_TYPES)} "
                   f"(via TCGA_EXCLUDE_DATA_TYPES)")
    out.append("")
    out.append("Average file size is the mean of the files actually downloaded "
               "(the `sampled` parenthetical in the file count column). Total "
               "data file size = average × number of files. Number of patients "
               "is the count of unique `patient_id`s with at least one file in "
               "this modality (exact when TCGA_MAX_FILES=0, undercounted when "
               "the per-modality download was capped).\n")

    # Markdown table — new column layout.
    header = ("| Rank | Category / Type / Workflow | Number of Data Files | "
              "Average File Size | Total Data File Size | Number of Patients | "
              "What it is |")
    sep    = "|---:|---|---:|---:|---:|---:|---|"
    out.append(header)
    out.append(sep)
    for i, r in enumerate(rows, 1):
        ctw  = f"{r['category']} / {r['data_type']} / {r['workflow']}"
        nfiles = (f"{r['n_files_total']} (sampled {r['sampled']})"
                  if r['sampled'] and r['sampled'] < r['n_files_total']
                  else str(r['n_files_total']))
        desc = _describe_modality(r["data_type"])
        out.append(
            f"| {i} | {ctw} | {nfiles} | {_fmt_bytes(r['mean_file_bytes'])} | "
            f"{_fmt_bytes(r['total_bytes'])} | {r['n_patients']} | {desc} |"
        )

    total_proj = sum((r["total_bytes"] or 0) for r in rows)
    out.append("")
    out.append(f"**Project total data size (sum of measured rows):** "
               f"{_fmt_bytes(total_proj)}")

    summary_path = PROJECT_DIR / "size_summary.md"
    summary_path.write_text("\n".join(out) + "\n")
    print(f"  [size-summary] wrote {summary_path} ({len(rows)} modalities, "
          f"~{_fmt_bytes(total_proj)} total)", flush=True)


if __name__ == "__main__":
    try:
        run_agent()
    finally:
        _write_project_rollups()
        _write_size_summary()
