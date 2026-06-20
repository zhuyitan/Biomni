#!/usr/bin/env python3
"""
Convert assembled matrix TSV files to Apache Parquet (ZSTD-compressed).

Purpose
-------
The pan-cancer matrix files emitted by the assemble_*.py scripts are tab-
delimited text. The largest one (`dnam_sesame_450k.beta_value.txt`) is ~43 GB.
Storing the same data as Parquet with ZSTD compression and float32 dtype
typically shrinks each file 5-10x and makes it 10-100x faster to read into
pandas with one line: `pd.read_parquet(...)`.

Behavior
--------
The matrix files in `have/data/tcga/data/_assembled/` all have the same layout:
    col 1                   = the feature key (string), e.g. peptide_target,
                              IlmnID, miRNA_ID, gene_id+...
    col 2..N (sample cols)  = numeric data values

This script reads each input in row-chunks (streaming, so a 43 GB file does
not have to fit in memory), converts the data columns to the requested dtype
(default float32), and appends each chunk as a row group to a Parquet writer.
The output is `<input_basename>.parquet` written next to the input.

Originals (TSV) are kept untouched. By default, an existing `.parquet` file is
SKIPPED (use --overwrite to re-convert).

Discovery
---------
With no `--files` argument, the script scans `--matrix-dir` (default
`have/data/tcga/data/_assembled/`) for `*.txt` files, excluding anything with
`metadata` in the name and anything under an `annotation/` subdirectory.

CLI
---
    # convert all matrix files in the default directory
    python have/data/tcga/scripts/convert_to_parquet.py

    # convert specific files
    python have/data/tcga/scripts/convert_to_parquet.py --files path/to/foo.txt path/to/bar.txt

    # list what would be converted without doing it
    python have/data/tcga/scripts/convert_to_parquet.py --dry-run

    # options:
    #   --matrix-dir <dir>            default: have/data/tcga/data/_assembled
    #   --dtype {float32,float64}     default: float32
    #   --compression {zstd,snappy,gzip}  default: zstd
    #   --chunksize <int>             default: 10000  (rows per read chunk)
    #   --overwrite                   re-convert even if .parquet exists
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pcsv
import pyarrow.parquet as pq


DEFAULT_MATRIX_DIR = str(Path(__file__).resolve().parent.parent / "data" / "_assembled")
DEFAULT_CHUNKSIZE  = 10_000


# Columns that hold gene/feature metadata (string or integer), NOT data values.
# Anything not in this set is treated as a numeric data column.
GENE_INFO_STRING_COLS  = {"gene_id", "gene_name", "chromosome", "gene_type",
                          "peptide_target", "IlmnID", "miRNA_ID"}
GENE_INFO_INTEGER_COLS = {"start", "end"}


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def discover_matrix_files(matrix_dir: Path) -> list:
    """Find *.txt files in matrix_dir, excluding metadata and annotation files."""
    out = []
    for f in sorted(matrix_dir.glob("*.txt")):
        if "metadata" in f.name.lower():
            continue
        out.append(f)
    return out


def build_dtype_map(header_cols: list, value_dtype: str) -> dict:
    """For a matrix header like ['IlmnID', '<uuid1>', '<uuid2>', ...] return
    a {col_name: dtype} map. Known gene-info cols get string/Int64; sample-id
    cols get the chosen value dtype."""
    dtypes = {}
    for c in header_cols:
        if c in GENE_INFO_STRING_COLS:
            dtypes[c] = "string"
        elif c in GENE_INFO_INTEGER_COLS:
            dtypes[c] = "Int64"
        else:
            dtypes[c] = value_dtype
    return dtypes


def convert_one(in_path: Path, dtype: str, compression: str,
                chunksize: int, overwrite: bool, infer_dtypes: bool = False) -> dict:
    """Convert one TSV matrix to Parquet. Returns a dict with stats.

    If infer_dtypes=True, the matrix-style dtype map is skipped and pandas
    auto-detects each column's type. This is needed for files with many
    heterogeneous columns whose names are not in the known gene-info set
    (e.g., long-format mutation MAFs with VEP annotation columns)."""
    out_path = in_path.with_suffix(".parquet")
    tmp_path = out_path.with_suffix(".parquet.tmp")

    if out_path.exists() and not overwrite:
        return {"input": in_path, "output": out_path, "skipped": True,
                "in_bytes": in_path.stat().st_size, "out_bytes": out_path.stat().st_size,
                "elapsed_s": 0.0, "n_rows": None, "n_cols": None}

    if tmp_path.exists():
        tmp_path.unlink()

    # Discover column names (always needed for the n_cols report).
    header = pd.read_csv(in_path, sep="\t", nrows=0)
    header_cols = list(header.columns)

    t0 = time.time()
    n_rows = 0

    if infer_dtypes:
        # Use pyarrow's native CSV reader — keeps a single schema across all
        # blocks, which sidesteps the schema-drift error pandas produces when
        # different chunks infer different dtypes for sparse columns.
        # Block size of 64 MB usually contains thousands of rows even for wide
        # tables (e.g., ~2K rows for the 10,597-col mutation-by-case file).
        read_opts = pcsv.ReadOptions(block_size=64 * 1024 * 1024)
        parse_opts = pcsv.ParseOptions(delimiter="\t")
        convert_opts = pcsv.ConvertOptions(
            strings_can_be_null=True,
            null_values=["NA", "NaN", ""],
        )
        writer = None
        try:
            with pcsv.open_csv(in_path,
                               read_options=read_opts,
                               parse_options=parse_opts,
                               convert_options=convert_opts) as reader:
                for batch in reader:
                    if writer is None:
                        writer = pq.ParquetWriter(tmp_path, batch.schema,
                                                  compression=compression)
                    writer.write_batch(batch)
                    n_rows += batch.num_rows
        finally:
            if writer is not None:
                writer.close()
    else:
        # Original matrix-style path: pandas + per-known-col dtype map.
        dtype_map = build_dtype_map(header_cols, dtype)
        writer = None
        try:
            reader = pd.read_csv(
                in_path, sep="\t",
                dtype=dtype_map,
                chunksize=chunksize,
                na_values=["NA", "NaN", ""],
                keep_default_na=True,
                low_memory=False,
            )
            for chunk in reader:
                table = pa.Table.from_pandas(chunk, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(tmp_path, table.schema,
                                              compression=compression)
                writer.write_table(table)
                n_rows += len(chunk)
        finally:
            if writer is not None:
                writer.close()

    if not tmp_path.exists():
        raise RuntimeError(f"no data written for {in_path}")
    tmp_path.rename(out_path)

    return {
        "input": in_path, "output": out_path, "skipped": False,
        "in_bytes": in_path.stat().st_size,
        "out_bytes": out_path.stat().st_size,
        "elapsed_s": time.time() - t0,
        "n_rows": n_rows, "n_cols": len(header_cols),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="+", default=None,
                    help="Explicit list of TSV files to convert. Overrides --matrix-dir.")
    ap.add_argument("--matrix-dir", default=DEFAULT_MATRIX_DIR,
                    help=f"Directory to auto-scan for matrix .txt files "
                         f"(default: {DEFAULT_MATRIX_DIR}).")
    ap.add_argument("--dtype", default="float32", choices=["float32", "float64"],
                    help="Storage dtype for data-value columns (default: float32).")
    ap.add_argument("--compression", default="zstd",
                    choices=["zstd", "snappy", "gzip", "brotli", "lz4", "none"],
                    help="Parquet compression (default: zstd).")
    ap.add_argument("--chunksize", type=int, default=DEFAULT_CHUNKSIZE,
                    help=f"Row-chunk size for streaming (default: {DEFAULT_CHUNKSIZE}).")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-convert even if the .parquet output already exists.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List files that would be converted; do nothing.")
    ap.add_argument("--infer-dtypes", action="store_true",
                    help="Skip the matrix-style dtype map (string-key col + numeric value cols) "
                         "and let pandas auto-detect each column's type. Needed for files with "
                         "heterogeneous mixed-type columns (e.g., long-format mutation MAFs, "
                         "wide mutation-by-case tables with both string desc cols and 0/1 cols).")
    args = ap.parse_args()

    # Resolve input file list
    if args.files:
        files = [Path(f) for f in args.files]
        missing = [f for f in files if not f.exists()]
        if missing:
            print(f"[error] missing input file(s): {missing}", file=sys.stderr)
            sys.exit(1)
    else:
        matrix_dir = Path(args.matrix_dir)
        if not matrix_dir.is_dir():
            print(f"[error] --matrix-dir does not exist: {matrix_dir}", file=sys.stderr)
            sys.exit(1)
        files = discover_matrix_files(matrix_dir)
        if not files:
            print(f"[error] no matrix .txt files found in {matrix_dir} "
                  f"(after excluding *metadata* and annotation/)", file=sys.stderr)
            sys.exit(1)

    print(f"[plan] {len(files)} file(s) to convert"
          f" (dtype={args.dtype}, compression={args.compression}, chunksize={args.chunksize}):",
          flush=True)
    for f in files:
        out = f.with_suffix(".parquet")
        marker = "  exists -> SKIP" if (out.exists() and not args.overwrite) else ""
        print(f"  {human_bytes(f.stat().st_size):>10}  {f}{marker}", flush=True)

    if args.dry_run:
        print("[dry-run] not converting.", flush=True)
        return

    total_in = total_out = 0
    n_done = n_skip = 0
    overall_t0 = time.time()
    for f in files:
        print(f"\n[convert] {f}", flush=True)
        try:
            r = convert_one(f, args.dtype, args.compression, args.chunksize, args.overwrite,
                            infer_dtypes=args.infer_dtypes)
        except Exception as e:
            print(f"  [error] {e}", flush=True)
            continue
        if r["skipped"]:
            n_skip += 1
            print(f"  [skip] output already exists: {r['output']} ({human_bytes(r['out_bytes'])})",
                  flush=True)
        else:
            n_done += 1
            ratio = r["in_bytes"] / r["out_bytes"] if r["out_bytes"] else 0.0
            print(f"  [done] {r['n_rows']:,} rows x {r['n_cols']:,} cols in {r['elapsed_s']:.1f}s",
                  flush=True)
            print(f"         {human_bytes(r['in_bytes'])}  ->  {human_bytes(r['out_bytes'])}"
                  f"   ({ratio:.1f}x compression)", flush=True)
        total_in  += r["in_bytes"]
        total_out += r["out_bytes"]

    overall_t = time.time() - overall_t0
    overall_ratio = total_in / total_out if total_out else 0.0
    print(f"\n[summary] converted={n_done}, skipped={n_skip}, elapsed={overall_t:.1f}s",
          flush=True)
    print(f"          total IN : {human_bytes(total_in):>10}", flush=True)
    print(f"          total OUT: {human_bytes(total_out):>10}   ({overall_ratio:.1f}x overall)",
          flush=True)


if __name__ == "__main__":
    main()
