#!/usr/bin/env python3
"""
Assemble pan-cancer SeSAMe DNA methylation beta-value matrices, ONE PER ARRAY
PLATFORM, from per-sample TCGA files downloaded by tcga_extractor_agent.py.

TCGA methylation data was generated on three Illumina array platforms over the
years. GDC reprocessed all of them through the same SeSAMe workflow, so all
three end up in the same `Methylation_Beta_Value/` folder. We split them apart
by file size (the probe count differs by an order of magnitude per platform):

  Platform   probes/file    typical file size
  -------    -----------    -----------------
  27K        ~27,578        ~0.7-1 MB
  450K       ~486,427       ~12-13 MB
  EPIC v2    ~930,659       ~23-25 MB

Inputs (per project):
  <TCGA_ROOT>/TCGA-<PROJECT>/DNA_Methylation/Methylation_Beta_Value/
    SeSAMe_Methylation_Beta_Estimation.manifest.tsv
    <file_uuid>/<file_name>.methylation_array.sesame.level3betas.txt

Outputs (tab-delimited):
  <OUT_DIR>/dnam_sesame_27k.beta_value.txt       HM27 probes x samples
  <OUT_DIR>/dnam_sesame_450k.beta_value.txt      HM450 probes x samples
  <OUT_DIR>/dnam_sesame_epic_v2.beta_value.txt   EPIC v2 probes x samples
  <OUT_DIR>/dnam_sesame.metadata.txt             one row per file_uuid
                                                 (covers all three platforms;
                                                  has an `array_platform` column)

Each per-platform matrix:
  * First column header: `IlmnID`
  * Subsequent columns: one per file_uuid (column header == file UUID)
  * Probe order: canonical, set by the FIRST file of that platform encountered
  * Probe-order consistency is enforced via the IlmnID column. Files whose
    probe order differs from the platform canonical are reindexed onto the
    canonical key. Extras are dropped (logged); missing canonical probes
    become NaN (logged). Within a single platform this is rarely needed since
    every file from the same array should have identical probes in identical
    order, but it's checked and logged for safety.

Metadata table (single file across all platforms):
  Same columns as the CN/GE/miRNA metadata tables, plus one extra column:
    array_platform: "27K", "450K", or "EPIC v2"

The TCGA sample-type and TSS lookups, plus barcode parsing helpers, are
imported from assemble_cnv_ascat3.py so all assemblers stay in sync.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_cnv_ascat3 import (  # noqa: E402
    SAMPLE_TYPE_DEFINITION,
    TSS_STUDY_NAME,
    parse_sample_barcode,
    pick_tumor_and_normal,
)


FEATURE_KEY_COL = "IlmnID"
VALUE_COL       = "beta_value"

# Platform definitions: label used in metadata + filename slug + size threshold
# (max file size, in bytes, for that platform — first match wins in PLATFORM_ORDER).
PLATFORMS = {
    "27K":     {"slug": "27k",     "max_bytes":  4 * 1024 * 1024},  # < 4 MB
    "450K":    {"slug": "450k",    "max_bytes": 18 * 1024 * 1024},  # 4-18 MB
    "EPIC v2": {"slug": "epic_v2", "max_bytes": float("inf")},      # > 18 MB
}
PLATFORM_ORDER = ["27K", "450K", "EPIC v2"]


def classify_platform(file_size_bytes: int) -> str:
    """Identify methylation array platform from level-3 beta TXT file size."""
    for p in PLATFORM_ORDER:
        if file_size_bytes < PLATFORMS[p]["max_bytes"]:
            return p
    return PLATFORM_ORDER[-1]  # unreachable; defensive


def build_feature_key(df: pd.DataFrame) -> pd.Series:
    return df[FEATURE_KEY_COL].astype(str)


def load_one(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=[FEATURE_KEY_COL, VALUE_COL],
        dtype={FEATURE_KEY_COL: "string", VALUE_COL: "float32"},
        na_values=["", "NA", "NaN"],
        keep_default_na=True,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tcga-root",
                    default=str(Path(__file__).resolve().parent.parent / "data"),
                    help="Root containing TCGA-<PROJECT>/ folders (default: %(default)s).")
    ap.add_argument("--out-dir",
                    default=str(Path(__file__).resolve().parent.parent / "data" / "_assembled"),
                    help="Output directory (default: %(default)s).")
    ap.add_argument("--projects", nargs="*", default=None,
                    help="Subset of TCGA-* projects to assemble. Default: all that have SeSAMe Methylation Beta Value.")
    args = ap.parse_args()

    tcga_root = Path(args.tcga_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(tcga_root.glob(
        "TCGA-*/DNA_Methylation/Methylation_Beta_Value/SeSAMe_Methylation_Beta_Estimation.manifest.tsv"
    ))
    if args.projects:
        wanted = set(args.projects)
        manifests = [m for m in manifests if m.parts[-4] in wanted]
    if not manifests:
        print(f"[error] no SeSAMe_Methylation_Beta_Estimation.manifest.tsv found under {tcga_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[discover] {len(manifests)} project manifest(s):", flush=True)
    for m in manifests:
        print(f"            {m.parts[-4]}", flush=True)

    # Per-platform state buckets
    state = {
        p: {
            "canonical_key": None,
            "canonical_features_df": None,
            "columns": {},                   # file_uuid -> aligned pd.Series
            "n_reordered": 0,
            "n_dropped_features": 0,
            "n_missing_in_file": 0,
        }
        for p in PLATFORM_ORDER
    }
    meta_rows = []   # one entry per file_uuid (any platform)

    for manifest_path in manifests:
        project = manifest_path.parts[-4]
        gln_dir = manifest_path.parent
        man = pd.read_csv(manifest_path, sep="\t", dtype=str)
        print(f"[{project}] {len(man)} files in manifest", flush=True)

        for _, row in man.iterrows():
            file_uuid = row["file_id"]
            file_name = row["file_name"]
            file_path = gln_dir / file_uuid / file_name
            if not file_path.exists():
                print(f"  [skip] missing: {file_path}", flush=True)
                continue

            platform = classify_platform(file_path.stat().st_size)
            s = state[platform]

            tumor_bc, normal_bc = pick_tumor_and_normal(row.get("sample_barcode"))
            parsed = parse_sample_barcode(tumor_bc) if tumor_bc else {}

            try:
                df = load_one(file_path)
            except Exception as e:
                print(f"  [error] {file_uuid}: read failed: {e}", flush=True)
                continue

            file_key = build_feature_key(df)

            if s["canonical_key"] is None:
                s["canonical_features_df"] = df[[FEATURE_KEY_COL]].reset_index(drop=True)
                s["canonical_key"] = build_feature_key(s["canonical_features_df"]).reset_index(drop=True)
                print(f"  [{platform}][canonical] probe order set from {file_uuid}: {len(s['canonical_key'])} probes", flush=True)
                s["columns"][file_uuid] = df[VALUE_COL].astype("float32").reset_index(drop=True)
            else:
                canonical_key = s["canonical_key"]
                same_len = len(file_key) == len(canonical_key)
                same_order = same_len and (file_key.values == canonical_key.values).all()
                if same_order:
                    s["columns"][file_uuid] = df[VALUE_COL].astype("float32").reset_index(drop=True)
                else:
                    df2 = df.copy()
                    df2["__key__"] = file_key.values
                    before = len(df2)
                    df2 = df2.drop_duplicates(subset="__key__", keep="first")
                    if len(df2) != before:
                        print(f"  [{platform}][warn] {file_uuid}: dropped {before - len(df2)} duplicate probe keys", flush=True)
                    df2 = df2.set_index("__key__")
                    extra = set(df2.index.tolist()) - set(canonical_key.values.tolist())
                    if extra:
                        s["n_dropped_features"] += len(extra)
                        print(f"  [{platform}][warn] {file_uuid}: {len(extra)} probe(s) in this file are not in canonical order; "
                              f"dropping (first example: {next(iter(extra))})", flush=True)
                    aligned = df2.reindex(canonical_key.values)[VALUE_COL]
                    n_new_na = int(aligned.isna().sum() - df[VALUE_COL].isna().sum())
                    if n_new_na > 0:
                        s["n_missing_in_file"] += 1
                        print(f"  [{platform}][warn] {file_uuid}: {n_new_na} canonical probe(s) missing in this file (set to NA)", flush=True)
                    s["columns"][file_uuid] = aligned.astype("float32").reset_index(drop=True)
                    s["n_reordered"] += 1
                    print(f"  [{platform}][reorder] {file_uuid}: probe order differs from canonical; reindexed onto canonical key", flush=True)

            meta_rows.append({
                "file_uuid": file_uuid,
                "file_name": file_name,
                "cancer_type": project.replace("TCGA-", ""),
                "study_name": parsed.get("study_name"),
                "patient_barcode": row.get("patient_id"),
                "sample_barcode": tumor_bc,
                "sample_type": parsed.get("sample_type"),
                "is_tumor": parsed.get("is_tumor"),
                "is_normal": parsed.get("is_normal"),
                "is_metastatic": parsed.get("is_metastatic"),
                "matched_normal_barcode": normal_bc,  # always None for SeSAMe methylation
                "data_category": row.get("data_category"),
                "data_type": row.get("data_type"),
                "workflow_type": row.get("workflow_type"),
                "md5sum": row.get("md5sum"),
                "array_platform": platform,
            })

    # ---- Summary -------------------------------------------------------------
    total_loaded = sum(len(state[p]["columns"]) for p in PLATFORM_ORDER)
    print(f"[assemble] total files loaded: {total_loaded}", flush=True)
    for p in PLATFORM_ORDER:
        s = state[p]
        n_files = len(s["columns"])
        n_features = len(s["canonical_features_df"]) if s["canonical_features_df"] is not None else 0
        print(f"  {p:>8}: {n_files:>5} files; {n_features:>6} probes; "
              f"{s['n_reordered']} reordered; {s['n_dropped_features']} extra-probe drops; "
              f"{s['n_missing_in_file']} files with missing canonical probes", flush=True)

    # ---- Write a matrix per platform ----------------------------------------
    for p in PLATFORM_ORDER:
        s = state[p]
        if not s["columns"]:
            print(f"  [skip-write] {p}: no files loaded", flush=True)
            continue
        matrix_df = pd.concat(
            [s["canonical_features_df"].reset_index(drop=True), pd.DataFrame(s["columns"])],
            axis=1,
        )
        out_matrix = out_dir / f"dnam_sesame_{PLATFORMS[p]['slug']}.beta_value.txt"
        n_samples = matrix_df.shape[1] - 1
        print(f"[write] {out_matrix} ({matrix_df.shape[0]} probes x {n_samples} samples)", flush=True)
        matrix_df.to_csv(out_matrix, sep="\t", index=False, na_rep="NA")

    # ---- Write a single metadata file (covers all platforms) ----------------
    meta_df = pd.DataFrame(meta_rows)
    out_meta = out_dir / "dnam_sesame.metadata.txt"
    print(f"[write] {out_meta}  ({len(meta_df)} rows)", flush=True)
    meta_df.to_csv(out_meta, sep="\t", index=False, na_rep="NA")


if __name__ == "__main__":
    main()
