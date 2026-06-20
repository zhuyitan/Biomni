#!/usr/bin/env python3
"""
Assemble a pan-cancer RPPA protein-expression matrix from per-sample TCGA
files downloaded by tcga_extractor_agent.py.

Inputs (per project):
  <TCGA_ROOT>/TCGA-<PROJECT>/Proteome_Profiling/Protein_Expression_Quantification/
    manifest.tsv
    <file_uuid>/<file_name>_RPPA_data.tsv

Per-file format (6 columns):
  AGID, lab_id, catalog_number, set_id, peptide_target, protein_expression

Outputs (tab-delimited):
  <OUT_DIR>/rppa.protein_expression.txt   antibodies x samples; peptide_target col + one col per file_uuid
  <OUT_DIR>/rppa.metadata.txt             one row per file_uuid (sample/patient/cancer/...)

Key safeguards (parallel to the CN/GE/miRNA/DNAm assemblers):
  * Per-file `protein_expression` ONLY (AGID/lab_id/catalog/set_id are ignored
    for the matrix; they live in the separate annotation file).
  * Antibody-order consistency is enforced via the `peptide_target` column.
    Files with a differing order are reindexed onto the canonical key; extras
    dropped and missing canonical antibodies set to NaN (all logged). For RPPA
    the panel is uniform across the cohort (verified to be the same 487
    antibodies in all 7,906 files), so warnings here would indicate a problem.
  * RPPA manifests have a single aliquot barcode per file (no matched normal),
    so the `matched_normal_barcode` field in the metadata table is always NA
    (kept for column parity with the other assemblers' metadata).

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


FEATURE_KEY_COL = "peptide_target"
VALUE_COL       = "protein_expression"


def build_feature_key(df: pd.DataFrame) -> pd.Series:
    return df[FEATURE_KEY_COL].astype(str)


def load_one(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        sep="\t",
        usecols=[FEATURE_KEY_COL, VALUE_COL],
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
                    help="Subset of TCGA-* projects to assemble. Default: all that have RPPA data.")
    args = ap.parse_args()

    tcga_root = Path(args.tcga_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(tcga_root.glob(
        "TCGA-*/Proteome_Profiling/Protein_Expression_Quantification/manifest.tsv"
    ))
    if args.projects:
        wanted = set(args.projects)
        manifests = [m for m in manifests if m.parts[-4] in wanted]
    if not manifests:
        print(f"[error] no RPPA manifest.tsv found under {tcga_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[discover] {len(manifests)} project manifest(s):", flush=True)
    for m in manifests:
        print(f"            {m.parts[-4]}", flush=True)

    canonical_key = None          # pd.Series, the canonical peptide_target order
    canonical_features_df = None  # DataFrame with peptide_target col in canonical order
    columns = {}                  # file_uuid -> aligned pd.Series (float32)
    meta_rows = []
    n_reordered = n_dropped_features = n_missing_in_file = 0

    for manifest_path in manifests:
        project = manifest_path.parts[-4]
        rdir = manifest_path.parent
        man = pd.read_csv(manifest_path, sep="\t", dtype=str)
        print(f"[{project}] {len(man)} files in manifest", flush=True)

        for _, row in man.iterrows():
            file_uuid = row["file_id"]
            file_name = row["file_name"]
            file_path = rdir / file_uuid / file_name
            if not file_path.exists():
                print(f"  [skip] missing: {file_path}", flush=True)
                continue

            # RPPA manifests have a single aliquot barcode per file (no matched normal).
            tumor_bc, normal_bc = pick_tumor_and_normal(row.get("sample_barcode"))
            parsed = parse_sample_barcode(tumor_bc) if tumor_bc else {}

            try:
                df = load_one(file_path)
            except Exception as e:
                print(f"  [error] {file_uuid}: read failed: {e}", flush=True)
                continue

            file_key = build_feature_key(df)

            if canonical_key is None:
                canonical_features_df = df[[FEATURE_KEY_COL]].reset_index(drop=True)
                canonical_key = build_feature_key(canonical_features_df).reset_index(drop=True)
                print(f"  [canonical] antibody order set from {file_uuid}: {len(canonical_key)} antibodies", flush=True)
                columns[file_uuid] = df[VALUE_COL].astype("float32").reset_index(drop=True)
            else:
                same_len = len(file_key) == len(canonical_key)
                same_order = same_len and (file_key.values == canonical_key.values).all()
                if same_order:
                    columns[file_uuid] = df[VALUE_COL].astype("float32").reset_index(drop=True)
                else:
                    df2 = df.copy()
                    df2["__key__"] = file_key.values
                    before = len(df2)
                    df2 = df2.drop_duplicates(subset="__key__", keep="first")
                    if len(df2) != before:
                        print(f"  [warn] {file_uuid}: dropped {before - len(df2)} duplicate antibody keys", flush=True)
                    df2 = df2.set_index("__key__")
                    extra = set(df2.index.tolist()) - set(canonical_key.values.tolist())
                    if extra:
                        n_dropped_features += len(extra)
                        print(f"  [warn] {file_uuid}: {len(extra)} antibody(ies) in this file are not in canonical order; "
                              f"dropping (first example: {next(iter(extra))})", flush=True)
                    aligned = df2.reindex(canonical_key.values)[VALUE_COL]
                    n_new_na = int(aligned.isna().sum() - df[VALUE_COL].isna().sum())
                    if n_new_na > 0:
                        n_missing_in_file += 1
                        print(f"  [warn] {file_uuid}: {n_new_na} canonical antibody(ies) missing in this file (set to NA)", flush=True)
                    columns[file_uuid] = aligned.astype("float32").reset_index(drop=True)
                    n_reordered += 1
                    print(f"  [reorder] {file_uuid}: antibody order differs from canonical; reindexed onto canonical key", flush=True)

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
                "matched_normal_barcode": normal_bc,  # always None/empty for RPPA
                "data_category": row.get("data_category"),
                "data_type": row.get("data_type"),
                "workflow_type": row.get("workflow_type"),
                "md5sum": row.get("md5sum"),
            })

    if canonical_features_df is None:
        print("[error] no files loaded", file=sys.stderr)
        sys.exit(1)

    print(f"[assemble] {len(columns)} files; {len(canonical_features_df)} antibodies; "
          f"{n_reordered} files reordered; {n_dropped_features} extra-antibody drops; "
          f"{n_missing_in_file} files had missing canonical antibodies", flush=True)

    matrix_df = pd.concat(
        [canonical_features_df.reset_index(drop=True), pd.DataFrame(columns)],
        axis=1,
    )
    meta_df = pd.DataFrame(meta_rows)

    out_matrix = out_dir / "rppa.protein_expression.txt"
    out_meta   = out_dir / "rppa.metadata.txt"
    n_samples = matrix_df.shape[1] - 1  # one feature column
    print(f"[write] {out_matrix} ({matrix_df.shape[0]} antibodies x {n_samples} samples)", flush=True)
    matrix_df.to_csv(out_matrix, sep="\t", index=False, na_rep="NA")
    print(f"[write] {out_meta}  ({len(meta_df)} rows)", flush=True)
    meta_df.to_csv(out_meta, sep="\t", index=False, na_rep="NA")


if __name__ == "__main__":
    main()
