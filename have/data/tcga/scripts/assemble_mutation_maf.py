#!/usr/bin/env python3
"""
Assemble a pan-cancer somatic-mutation MAF table from per-sample TCGA files
downloaded by tcga_extractor_agent.py.

Inputs (per project):
  <TCGA_ROOT>/TCGA-<PROJECT>/Simple_Nucleotide_Variation/Masked_Somatic_Mutation/
    Aliquot_Ensemble_Somatic_Variant_Merging_and_Masking.manifest.tsv
    <file_uuid>/<file_name>.wxs.aliquot_ensemble_masked.maf.gz

Per-file format (verified across 32 projects, 9,648 files):
  Lines 1-7 : comment lines starting with #  (gdc version, contigs, dates,
              normal.aliquot UUID, tumor.aliquot UUID)
  Line 8    : column header (140 tab-separated columns; identical across the
              entire cohort)
  Lines 9+  : one tab-delimited mutation per line (data rows)

Outputs (tab-delimited):
  <OUT_DIR>/mutation.maf.txt         pan-cancer concatenated mutation table
                                     (long format; first col is the canonical
                                      union of every file's columns, sample
                                      identity is in `Tumor_Sample_UUID` /
                                      `Tumor_Sample_Barcode` columns)
  <OUT_DIR>/mutation.metadata.txt    one row per file_uuid; same column layout
                                     as the CN/GE/miRNA/DNAm/RPPA metadata
                                     tables plus a `Tumor_Sample_UUID` column
                                     (the join key into mutation.maf.txt)

Decompression: each .maf.gz is decompressed to a sibling .maf file (kept
alongside the .maf.gz) so plain-text MAFs are available for other tools. Skip
the decompression if the .maf is already present, unless --decompress-overwrite
is set.

Column-union safeguard (parallel to gene-order safeguards in other assemblers):
  * PASS 1 scans the header of every MAF and computes the union of column
    names (preserving first-seen order). Files whose headers differ from the
    canonical (first file's) header are logged.
  * PASS 2 streams each MAF's data rows into the output, reindexing the
    columns to the union order — extra cells become "" (empty string), missing
    cells the same.

In practice every file in the current cohort has the same 140-column header,
so the union equals the canonical and the reindex is the identity (fast path
just streams data lines verbatim). The check + log still runs so any future
panel revision that adds/removes columns is detected.

The TCGA sample-type and TSS lookups, plus barcode parsing helpers, are
imported from assemble_cnv_ascat3.py so all assemblers stay in sync.
"""

import argparse
import gzip
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_cnv_ascat3 import (  # noqa: E402
    SAMPLE_TYPE_DEFINITION,
    TSS_STUDY_NAME,
    parse_sample_barcode,
    pick_tumor_and_normal,
)


N_COMMENT_LINES = 7   # GDC MAF spec: lines 1..7 are # comments; line 8 is the header


def decompress_to_maf(gz_path: Path, overwrite: bool) -> Path:
    """Decompress <name>.maf.gz to <name>.maf alongside it. Returns the .maf path.
    Skips work if the .maf already exists (unless overwrite=True)."""
    out_path = gz_path.with_suffix("")    # strip .gz, leaves <name>.maf
    if out_path.exists() and not overwrite:
        return out_path
    tmp_path = out_path.with_suffix(".maf.tmp")
    with gzip.open(gz_path, "rb") as fz, open(tmp_path, "wb") as fo:
        shutil.copyfileobj(fz, fo, length=1 << 20)
    tmp_path.rename(out_path)
    return out_path


def read_header_and_metadata(maf_path: Path):
    """Read a MAF file's header block + first data row and return
    (header_columns, tumor_uuid, tumor_barcode, normal_barcode).

    Reads only the first N_COMMENT_LINES + 2 lines, so it's cheap even on big MAFs.
    `tumor_uuid` comes from the `#tumor.aliquot <uuid>` comment line.
    `tumor_barcode` and `normal_barcode` come from the FIRST DATA ROW's
    Tumor_Sample_Barcode and Matched_Norm_Sample_Barcode columns. They will be
    None for empty MAFs (header only, no data rows)."""
    cols = None
    tumor_uuid = None
    tumor_bc = None
    normal_bc = None
    tb_idx = nb_idx = None
    with open(maf_path) as fh:
        for i, line in enumerate(fh):
            if i < N_COMMENT_LINES:
                s = line.rstrip("\n")
                if s.lower().startswith("#tumor.aliquot"):
                    parts = s.split()
                    if len(parts) >= 2:
                        tumor_uuid = parts[1].strip()
                continue
            if i == N_COMMENT_LINES:
                cols = line.rstrip("\n").split("\t")
                if "Tumor_Sample_Barcode" in cols:
                    tb_idx = cols.index("Tumor_Sample_Barcode")
                if "Matched_Norm_Sample_Barcode" in cols:
                    nb_idx = cols.index("Matched_Norm_Sample_Barcode")
                continue
            if i == N_COMMENT_LINES + 1:
                parts = line.rstrip("\n").split("\t")
                if tb_idx is not None and len(parts) > tb_idx:
                    tumor_bc = parts[tb_idx]
                if nb_idx is not None and len(parts) > nb_idx:
                    normal_bc = parts[nb_idx]
                break
    return cols, tumor_uuid, tumor_bc, normal_bc


# ---------------------------------------------------------------------------
# Mutation-by-case (binary) and gene-by-case (count) matrices
# ---------------------------------------------------------------------------

# A unique mutation feature is defined by these 7 columns (per user spec).
MUTATION_KEY_COLS = [
    "Chromosome", "Start_Position", "End_Position", "Strand",
    "Reference_Allele", "Tumor_Seq_Allele1", "Tumor_Seq_Allele2",
]

# Descriptor columns attached to each mutation in the mutation-by-case matrix.
# Order preserved per user spec.
MUTATION_DESC_COLS = [
    "Hugo_Symbol", "Entrez_Gene_Id", "NCBI_Build", "Chromosome",
    "Start_Position", "End_Position", "Strand",
    "Variant_Classification", "Variant_Type",
    "Reference_Allele", "Tumor_Seq_Allele1", "Tumor_Seq_Allele2",
    "dbSNP_RS", "Mutation_Status",
    "HGVSc", "HGVSp", "HGVSp_Short", "Transcript_ID", "Exon_Number",
    "all_effects", "Allele", "Gene", "Feature", "Feature_type",
    "One_Consequence", "Consequence",
    "cDNA_position", "CDS_position", "Protein_position",
    "Amino_acids", "Codons",
    "TRANSCRIPT_STRAND", "SYMBOL", "SYMBOL_SOURCE", "HGNC_ID", "BIOTYPE",
    "CANONICAL", "CCDS", "ENSP", "SWISSPROT", "UNIPARC", "UNIPROT_ISOFORM",
    "RefSeq", "MANE",
    "IMPACT", "VARIANT_CLASS",
    "COSMIC", "hotspot",
]

# Per spec, only these 9 protein-changing Variant_Classification values get
# counted in the gene-by-case matrix.
HIGH_IMPACT_VARIANT_CLASSES = {
    "Missense_Mutation", "Nonsense_Mutation",
    "Frame_Shift_Del", "Frame_Shift_Ins",
    "Splice_Site",
    "In_Frame_Del", "In_Frame_Ins",
    "Translation_Start_Site", "Nonstop_Mutation",
}


def build_matrices(maf_path: Path, out_dir: Path):
    """Build two additional output files from the assembled long-format MAF:
       (a) mutation.mutation_by_case.txt  -- binary mutation-by-case matrix +
                                            per-mutation description columns.
       (b) mutation.gene_by_case.txt      -- gene-by-case mutation-count matrix
                                            (only the 9 high-impact Variant_
                                            Classification categories count).

    The case identifier (column header in both matrices) is
        '<Tumor_Sample_Barcode>, <Matched_Norm_Sample_Barcode>'
    matching the `case` column in mutation.metadata.txt.
    """
    import numpy as np
    from scipy import sparse

    # Read only the columns we actually need from the (potentially huge) MAF.
    barcode_cols = ["Tumor_Sample_Barcode", "Matched_Norm_Sample_Barcode"]
    needed = list(dict.fromkeys(
        MUTATION_KEY_COLS + MUTATION_DESC_COLS + barcode_cols + ["Variant_Classification"]
    ))
    print(f"\n[matrices] reading {maf_path} (subset of {len(needed)} cols)...", flush=True)
    t0 = time.time()
    muts = pd.read_csv(maf_path, sep="\t", usecols=needed,
                       dtype=str, keep_default_na=False)
    print(f"[matrices] loaded {len(muts):,} rows in {time.time()-t0:.1f}s", flush=True)

    # Construct the case_id column matching the metadata table's `case` field.
    muts["case_id"] = muts["Tumor_Sample_Barcode"].astype(str) + ", " + muts["Matched_Norm_Sample_Barcode"].astype(str)

    # ---- (a) Mutation-by-case binary matrix ---------------------------------
    print(f"[matrices] building mutation-by-case (binary)...", flush=True)
    mut_key = muts[MUTATION_KEY_COLS].astype(str).agg("|".join, axis=1)
    mut_codes, unique_mut_keys = pd.factorize(mut_key, sort=False)   # first-seen order
    case_codes, unique_cases  = pd.factorize(muts["case_id"], sort=True)
    n_muts, n_cases = len(unique_mut_keys), len(unique_cases)
    print(f"  unique mutations: {n_muts:,}; unique cases: {n_cases:,}", flush=True)

    data = np.ones(len(muts), dtype=np.int8)
    binary_sparse = sparse.coo_matrix(
        (data, (mut_codes, case_codes)),
        shape=(n_muts, n_cases), dtype=np.int8,
    ).tocsr()
    # Cap at 1 (same (mutation, case) appearing in multiple rows -> still 1).
    binary_sparse.data = np.minimum(binary_sparse.data, 1)
    print(f"  binary matrix non-zeros: {binary_sparse.nnz:,} of {n_muts*n_cases:,} cells "
          f"({100*binary_sparse.nnz/max(1, n_muts*n_cases):.4f}% density)", flush=True)

    # Convert to dense DataFrame (may be heavy for pan-cancer).
    binary_dense = binary_sparse.toarray()
    binary_df = pd.DataFrame(binary_dense, columns=list(unique_cases))

    # Per-mutation descriptors: take the FIRST row's values for each unique key,
    # then reorder to match unique_mut_keys order.
    desc = muts[MUTATION_DESC_COLS].copy()
    desc["_mut_key"] = mut_key.values
    desc = desc.drop_duplicates(subset="_mut_key", keep="first")
    desc = desc.set_index("_mut_key").loc[list(unique_mut_keys)].reset_index(drop=True)

    final = pd.concat([desc, binary_df], axis=1)
    out_mbc = out_dir / "mutation.mutation_by_case.txt"
    print(f"[matrices] writing {out_mbc} ({final.shape[0]:,} rows x {final.shape[1]:,} cols)", flush=True)
    final.to_csv(out_mbc, sep="\t", index=False)

    # ---- (b) Gene-by-case mutation count matrix -----------------------------
    print(f"[matrices] building gene-by-case (count, high-impact only)...", flush=True)
    # All unique (Hugo_Symbol, Entrez_Gene_Id) pairs from the FULL data.
    unique_genes = muts[["Hugo_Symbol", "Entrez_Gene_Id"]].drop_duplicates().reset_index(drop=True)
    n_genes = len(unique_genes)
    print(f"  unique genes (from all rows): {n_genes:,}", flush=True)

    # Index lookup for genes and cases (cases reused from above).
    gene_to_idx = {(h, e): i for i, (h, e) in enumerate(
        zip(unique_genes["Hugo_Symbol"], unique_genes["Entrez_Gene_Id"]))}
    case_to_idx = {c: i for i, c in enumerate(unique_cases)}

    # Filter mutations to the 9 high-impact Variant_Classification categories.
    hi_mask = muts["Variant_Classification"].isin(HIGH_IMPACT_VARIANT_CLASSES)
    n_hi = int(hi_mask.sum())
    print(f"  high-impact mutations counted: {n_hi:,} of {len(muts):,} "
          f"({100*n_hi/max(1, len(muts)):.1f}%)", flush=True)
    hi = muts.loc[hi_mask, ["Hugo_Symbol", "Entrez_Gene_Id", "case_id"]]

    gene_idx = [gene_to_idx[(h, e)] for h, e in zip(hi["Hugo_Symbol"], hi["Entrez_Gene_Id"])]
    case_idx = [case_to_idx[c]      for c    in hi["case_id"]]
    data = np.ones(len(hi), dtype=np.int32)
    count_sparse = sparse.coo_matrix(
        (data, (gene_idx, case_idx)),
        shape=(n_genes, n_cases), dtype=np.int32,
    ).tocsr()    # duplicate (gene, case) pairs sum naturally on tocsr()
    print(f"  count matrix non-zeros: {count_sparse.nnz:,} of {n_genes*n_cases:,} cells "
          f"({100*count_sparse.nnz/max(1, n_genes*n_cases):.4f}% density)", flush=True)

    count_dense = count_sparse.toarray()
    count_df = pd.concat(
        [unique_genes.reset_index(drop=True),
         pd.DataFrame(count_dense, columns=list(unique_cases))],
        axis=1,
    )
    out_gbc = out_dir / "mutation.gene_by_case.txt"
    print(f"[matrices] writing {out_gbc} ({count_df.shape[0]:,} rows x {count_df.shape[1]:,} cols)", flush=True)
    count_df.to_csv(out_gbc, sep="\t", index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tcga-root",
                    default=str(Path(__file__).resolve().parent.parent / "data"),
                    help="Root containing TCGA-<PROJECT>/ folders (default: %(default)s).")
    ap.add_argument("--out-dir",
                    default=str(Path(__file__).resolve().parent.parent / "data" / "_assembled"),
                    help="Output directory (default: %(default)s).")
    ap.add_argument("--projects", nargs="*", default=None,
                    help="Subset of TCGA-* projects to assemble. Default: all that have MAFs.")
    ap.add_argument("--decompress-overwrite", action="store_true",
                    help="Re-decompress .maf.gz to .maf even if the .maf already exists.")
    args = ap.parse_args()

    tcga_root = Path(args.tcga_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(tcga_root.glob(
        "TCGA-*/Simple_Nucleotide_Variation/Masked_Somatic_Mutation/"
        "Aliquot_Ensemble_Somatic_Variant_Merging_and_Masking.manifest.tsv"
    ))
    if args.projects:
        wanted = set(args.projects)
        manifests = [m for m in manifests if m.parts[-4] in wanted]
    if not manifests:
        print(f"[error] no MAF manifests found under {tcga_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[discover] {len(manifests)} project manifest(s):", flush=True)
    for m in manifests:
        print(f"            {m.parts[-4]}", flush=True)

    # Discover all (project, manifest_row, maf_gz_path) tuples.
    file_records = []   # list of dicts: project, row, maf_gz, maf
    for manifest_path in manifests:
        project = manifest_path.parts[-4]
        man = pd.read_csv(manifest_path, sep="\t", dtype=str)
        for _, row in man.iterrows():
            maf_gz = manifest_path.parent / row["file_id"] / row["file_name"]
            if not maf_gz.exists():
                print(f"  [skip] missing .maf.gz: {maf_gz}", flush=True)
                continue
            file_records.append({"project": project, "row": row, "maf_gz": maf_gz})
        print(f"[{project}] {len(man)} files in manifest", flush=True)
    if not file_records:
        print("[error] no .maf.gz files found", file=sys.stderr)
        sys.exit(1)
    print(f"[total] {len(file_records)} .maf.gz files across {len(manifests)} project(s)", flush=True)

    # ---- PASS 1: decompress + read headers, build canonical column union ---
    t0 = time.time()
    canonical_cols = []          # union, preserved first-seen order
    canonical_set  = set()
    canonical_first_path = None  # for logging
    n_reordered = 0
    n_extra_cols_seen = 0
    n_missing_cols_seen = 0
    n_decomp = 0
    n_decomp_skipped = 0

    print(f"\n[pass1] decompressing .maf.gz -> .maf and scanning headers...", flush=True)
    for i, rec in enumerate(file_records):
        existed = rec["maf_gz"].with_suffix("").exists()
        rec["maf"] = decompress_to_maf(rec["maf_gz"], args.decompress_overwrite)
        if existed and not args.decompress_overwrite:
            n_decomp_skipped += 1
        else:
            n_decomp += 1

        cols, tumor_uuid, maf_tumor_bc, maf_normal_bc = read_header_and_metadata(rec["maf"])
        rec["cols"] = cols
        rec["tumor_uuid"] = tumor_uuid
        rec["maf_tumor_bc"] = maf_tumor_bc
        rec["maf_normal_bc"] = maf_normal_bc

        if cols is None:
            print(f"  [warn] {rec['maf']}: header could not be read (file may have <8 lines)", flush=True)
            continue

        if not canonical_cols:
            canonical_cols = list(cols)
            canonical_set = set(canonical_cols)
            canonical_first_path = rec["maf"]
            print(f"  [canonical] column order set from {rec['maf']}: {len(cols)} columns", flush=True)
        else:
            same_order = (cols == canonical_cols)
            file_set = set(cols)
            extra   = file_set - canonical_set
            missing = canonical_set - file_set
            if not same_order:
                n_reordered += 1
                msg_parts = []
                if extra:
                    n_extra_cols_seen += len(extra)
                    msg_parts.append(f"{len(extra)} new column(s)")
                if missing:
                    n_missing_cols_seen += len(missing)
                    msg_parts.append(f"{len(missing)} missing column(s)")
                if not msg_parts:
                    msg_parts.append("reordered only")
                print(f"  [warn] {rec['maf'].name}: header differs from canonical "
                      f"({', '.join(msg_parts)})", flush=True)
                # Extend canonical with new cols (preserve first-seen order)
                for c in cols:
                    if c not in canonical_set:
                        canonical_set.add(c)
                        canonical_cols.append(c)

        if (i + 1) % 1000 == 0:
            print(f"  [pass1] {i+1}/{len(file_records)} files scanned "
                  f"(elapsed {time.time()-t0:.1f}s)", flush=True)

    print(f"\n[pass1] done in {time.time()-t0:.1f}s: "
          f"{n_decomp} decompressed, {n_decomp_skipped} already-decompressed, "
          f"{n_reordered} files with header differences, "
          f"{n_extra_cols_seen} extra cols seen, {n_missing_cols_seen} missing cols seen", flush=True)
    print(f"[pass1] canonical column count: {len(canonical_cols)}", flush=True)

    # Locate Tumor_Seq_Allele1 / Tumor_Seq_Allele2 in canonical order so PASS 2
    # can normalize per-row allele ordering. Goal (per spec): after assembly,
    # Tumor_Seq_Allele1 >= Tumor_Seq_Allele2 (string compare) on EVERY row, so
    # (Chromosome, Start_Position, End_Position, Strand, Reference_Allele,
    #  Tumor_Seq_Allele1, Tumor_Seq_Allele2) uniquely identifies a mutation.
    try:
        idx_allele1 = canonical_cols.index("Tumor_Seq_Allele1")
        idx_allele2 = canonical_cols.index("Tumor_Seq_Allele2")
        do_allele_swap = True
        print(f"[allele-norm] will normalize Tumor_Seq_Allele1 >= Tumor_Seq_Allele2 "
              f"(canonical positions {idx_allele1}, {idx_allele2})", flush=True)
    except ValueError:
        idx_allele1 = idx_allele2 = None
        do_allele_swap = False
        print(f"[allele-norm][warn] Tumor_Seq_Allele1 or Tumor_Seq_Allele2 missing from canonical cols; "
              f"allele-swap normalization SKIPPED", flush=True)

    # ---- PASS 2: stream data rows to output, reindexing per file ---
    out_data = out_dir / "mutation.maf.txt"
    print(f"\n[pass2] writing {out_data}", flush=True)
    n_data_rows = 0
    n_files_streamed = 0
    n_same_layout = 0   # files whose header matched canonical exactly (no reindex needed)
    n_swapped = 0       # rows where Tumor_Seq_Allele1/2 were swapped
    t0 = time.time()
    n_canonical = len(canonical_cols)

    with open(out_data, "w") as out:
        out.write("\t".join(canonical_cols) + "\n")

        for rec in file_records:
            if not rec.get("cols"):
                continue
            file_cols = rec["cols"]
            same_layout = (file_cols == canonical_cols)
            n_file_cols = len(file_cols)
            if same_layout:
                n_same_layout += 1
                src_pos = None   # signal: no reindex needed
            else:
                # Build positional remap: for canonical pos k, which file pos to read?
                file_col_idx = {c: j for j, c in enumerate(file_cols)}
                src_pos = [file_col_idx.get(c, None) for c in canonical_cols]

            with open(rec["maf"]) as f:
                for i, line in enumerate(f):
                    if i < N_COMMENT_LINES + 1:   # skip 7 comments + 1 header
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if same_layout:
                        # Direct write but we still need to parse to apply the allele swap
                        if len(parts) < n_canonical:
                            parts.extend([""] * (n_canonical - len(parts)))
                    else:
                        # Pad source if MAF row has fewer fields than its header
                        if len(parts) < n_file_cols:
                            parts.extend([""] * (n_file_cols - len(parts)))
                        parts = [parts[p] if p is not None else "" for p in src_pos]

                    # Normalize allele ordering: ensure Tumor_Seq_Allele1 >= Tumor_Seq_Allele2
                    if do_allele_swap and parts[idx_allele1] < parts[idx_allele2]:
                        parts[idx_allele1], parts[idx_allele2] = parts[idx_allele2], parts[idx_allele1]
                        n_swapped += 1

                    out.write("\t".join(parts) + "\n")
                    n_data_rows += 1
            n_files_streamed += 1
            if n_files_streamed % 1000 == 0:
                print(f"  [pass2] {n_files_streamed}/{len(file_records)} files streamed, "
                      f"{n_data_rows:,} rows so far ({n_swapped:,} swapped) "
                      f"(elapsed {time.time()-t0:.1f}s)", flush=True)

    print(f"[pass2] done in {time.time()-t0:.1f}s: {n_files_streamed} files, "
          f"{n_data_rows:,} data rows; {n_same_layout}/{n_files_streamed} files had canonical layout; "
          f"{n_swapped:,} rows had Tumor_Seq_Allele1/2 swapped to satisfy Allele1 >= Allele2",
          flush=True)

    # ---- Build metadata table ---
    print(f"\n[metadata] building...", flush=True)
    meta_rows = []
    for rec in file_records:
        row = rec["row"]
        project = rec["project"]
        tumor_bc, normal_bc = pick_tumor_and_normal(row.get("sample_barcode"))
        parsed = parse_sample_barcode(tumor_bc) if tumor_bc else {}

        # Prefer the Tumor/Matched_Norm Sample_Barcode values pulled from the
        # MAF file itself; fall back to the manifest-derived pair if the MAF
        # had no data rows (in which case those will be None).
        case_tumor  = rec.get("maf_tumor_bc")  or tumor_bc
        case_normal = rec.get("maf_normal_bc") or normal_bc
        if case_tumor and case_normal:
            case_str = f"{case_tumor}, {case_normal}"
        elif case_tumor:
            case_str = case_tumor
        else:
            case_str = None

        meta_rows.append({
            "file_uuid": row["file_id"],
            "file_name": row["file_name"],
            "cancer_type": project.replace("TCGA-", ""),
            "study_name": parsed.get("study_name"),
            "patient_barcode": row.get("patient_id"),
            "sample_barcode": tumor_bc,
            "case": case_str,
            "sample_type": parsed.get("sample_type"),
            "is_tumor": parsed.get("is_tumor"),
            "is_normal": parsed.get("is_normal"),
            "is_metastatic": parsed.get("is_metastatic"),
            "matched_normal_barcode": normal_bc,
            "data_category": row.get("data_category"),
            "data_type": row.get("data_type"),
            "workflow_type": row.get("workflow_type"),
            "md5sum": row.get("md5sum"),
            "Tumor_Sample_UUID": rec.get("tumor_uuid"),
        })

    out_meta = out_dir / "mutation.metadata.txt"
    meta_df = pd.DataFrame(meta_rows)
    meta_df.to_csv(out_meta, sep="\t", index=False, na_rep="NA")
    print(f"[write] {out_meta}  ({len(meta_df):,} rows x {meta_df.shape[1]} cols)", flush=True)
    print(f"[write] {out_data} ({n_data_rows:,} data rows x {len(canonical_cols)} cols)", flush=True)

    # ---- Build mutation-by-case (binary) and gene-by-case (count) matrices --
    build_matrices(out_data, out_dir)


if __name__ == "__main__":
    main()
