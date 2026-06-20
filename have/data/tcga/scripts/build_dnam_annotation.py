#!/usr/bin/env python3
"""
Build tab-delimited DNA methylation probe annotation files from Illumina
methylation array manifests. Supports three platforms:

  450K     <- humanmethylation450_15017482_v1-2.csv  (text CSV)
  27K      <- humanmethylation27_270596_v1-2.bpm     (binary BPM with embedded CSV)
  EPIC v2  <- EPIC-8v2-0_A2.csv                       (text CSV)

Per-platform transformations:

* 450K and EPIC v2 (CSV manifests):
  - Strip the 7-line [Heading]/Loci-count overhead and the [Assay] marker.
  - Drop the single [Controls] section-marker line.
  - For every probe in the [Controls] section, prepend `ctl_` to the
    address (the first controls column) and put it in IlmnID. Other
    [Assay]-only columns stay empty for control rows.
  - For rows with multiple genes in UCSC_RefGene_Name (semicolon-separated),
    replicate the row n times. In the ith copy keep only the ith gene name,
    ith accession, ith location in UCSC_RefGene_Name / UCSC_RefGene_Accession
    / UCSC_RefGene_Group respectively. Other columns stay the same across copies.

* 27K (binary BPM manifest):
  - Skip the binary preamble and the [Heading] section entirely.
  - Use the [Assay] section + [Controls] section (drop the section-marker rows).
  - Insert a new column `TSS_group` immediately after `Distance_to_TSS`:
      Distance_to_TSS <= 200          -> "TSS200"
      200 < Distance_to_TSS <= 1500   -> "TSS1500"
      otherwise / empty / non-numeric -> "" (empty)
  - Strip the "GeneID:" prefix from the Gene_ID column (keep just the number).
  - For the Controls section, do not try to translate its column layout to
    the Assay's column layout — just append its rows positionally onto the
    Assay table. Prepend `ctl_` to the first column of each control row
    (the control probe id / address).

Output naming (under --annotation-dir):
  dnam_450k.annotation.txt
  dnam_27k.annotation.txt
  dnam_epic_v2.annotation.txt
"""

import argparse
import io
import sys
from pathlib import Path

import pandas as pd


REFGENE_COLS = ["UCSC_RefGene_Name", "UCSC_RefGene_Accession", "UCSC_RefGene_Group"]

PLATFORMS = {
    "450k":    {"manifest": "humanmethylation450_15017482_v1-2.csv",
                "output":   "dnam_450k.annotation.txt"},
    "27k":     {"manifest": "humanmethylation27_270596_v1-2.bpm",
                "output":   "dnam_27k.annotation.txt"},
    "epic_v2": {"manifest": "EPIC-8v2-0_A2.csv",
                "output":   "dnam_epic_v2.annotation.txt"},
}
PLATFORM_ORDER = ["450k", "27k", "epic_v2"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def find_section_lines(lines) -> dict:
    """Return {section_name: 0-indexed line number of the [Name] marker line}."""
    sections = {}
    for i, line in enumerate(lines):
        s = line.strip().rstrip(",").strip()
        if s.startswith("[") and s.endswith("]"):
            sections[s.strip("[]")] = i
    return sections


def _explode_refgene(df: pd.DataFrame, tag: str) -> pd.DataFrame:
    """For 450K / EPIC v2: replicate rows so each gene in UCSC_RefGene_Name
    gets its own row, paired with the matching UCSC_RefGene_Accession and
    UCSC_RefGene_Group entries."""
    name_lens = df["UCSC_RefGene_Name"].str.count(";")
    acc_lens  = df["UCSC_RefGene_Accession"].str.count(";")
    grp_lens  = df["UCSC_RefGene_Group"].str.count(";")
    mismatch = (name_lens != acc_lens) | (name_lens != grp_lens)
    if mismatch.any():
        n = int(mismatch.sum())
        first = df[mismatch].iloc[0]
        print(f"[{tag}][warn] {n} row(s) have mismatched ;-counts across UCSC_RefGene_* cols. "
              f"First example IlmnID={first['IlmnID']}: "
              f"Name='{first['UCSC_RefGene_Name']}', "
              f"Accession='{first['UCSC_RefGene_Accession']}', "
              f"Group='{first['UCSC_RefGene_Group']}'", flush=True)
        print(f"[{tag}][error] explode would fail on those rows; aborting.", file=sys.stderr)
        sys.exit(2)
    for c in REFGENE_COLS:
        df[c] = df[c].astype(str).str.split(";")
    return df.explode(REFGENE_COLS, ignore_index=True)


def _tss_group(dist) -> str:
    """27K: categorize Distance_to_TSS into TSS200 / TSS1500 / empty."""
    if dist is None:
        return ""
    s = str(dist).strip()
    if s == "" or s.lower() == "nan":
        return ""
    try:
        d = int(float(s))
    except (ValueError, TypeError):
        return ""
    if d <= 200:
        return "TSS200"
    if d <= 1500:
        return "TSS1500"
    return ""


def _read_csv_assay_controls(source, assay_marker: int, ctrl_marker: int):
    """Read the [Assay] section (with header) and [Controls] section (no header)
    from `source` (file path or StringIO). Returns (assay_df, ctrl_df).

    If passed a StringIO, the function takes care of seeking back to 0 between
    the two reads.
    """
    def _seek_if_buffer():
        if isinstance(source, io.IOBase):
            source.seek(0)

    _seek_if_buffer()
    assay = pd.read_csv(
        source,
        skiprows=assay_marker + 1,
        nrows=ctrl_marker - assay_marker - 2,
        dtype=str,
        low_memory=False,
        keep_default_na=False,
    )
    _seek_if_buffer()
    ctrl = pd.read_csv(
        source,
        skiprows=ctrl_marker + 1,
        header=None,
        dtype=str,
        low_memory=False,
        keep_default_na=False,
    )
    return assay, ctrl


# ---------------------------------------------------------------------------
# Per-platform builders
# ---------------------------------------------------------------------------

def build_450k_annotation(manifest_path: Path, out_path: Path):
    tag = "450k"
    print(f"[{tag}] parsing {manifest_path}", flush=True)

    with open(manifest_path) as fh:
        sections = find_section_lines(fh)
    if "Assay" not in sections or "Controls" not in sections:
        print(f"[{tag}][error] [Assay] / [Controls] markers not found", file=sys.stderr)
        sys.exit(1)
    assay_marker = sections["Assay"]
    ctrl_marker  = sections["Controls"]
    print(f"[{tag}] [Assay] at line {assay_marker + 1}; [Controls] at line {ctrl_marker + 1}", flush=True)

    assay, ctrl = _read_csv_assay_controls(manifest_path, assay_marker, ctrl_marker)
    print(f"[{tag}] read [Assay]    : {len(assay):,} rows x {assay.shape[1]} cols", flush=True)
    print(f"[{tag}] read [Controls] : {len(ctrl):,} rows x {ctrl.shape[1]} cols", flush=True)

    # Controls: only IlmnID (and Name as a mirror) populated; everything else blank.
    ctrl_df = pd.DataFrame("", index=range(len(ctrl)), columns=assay.columns)
    ctrl_df["IlmnID"] = "ctl_" + ctrl[0].astype(str)
    if "Name" in ctrl_df.columns:
        ctrl_df["Name"] = ctrl_df["IlmnID"]

    combined = pd.concat([assay, ctrl_df], ignore_index=True)
    print(f"[{tag}] combined: {len(combined):,} rows", flush=True)

    expanded = _explode_refgene(combined, tag)
    print(f"[{tag}] expanded: {len(combined):,} -> {len(expanded):,} rows "
          f"({len(expanded) - len(combined):,} extra from multi-gene probes)", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    expanded.to_csv(out_path, sep="\t", index=False, na_rep="")
    print(f"[{tag}] wrote {out_path}  ({len(expanded):,} rows x {expanded.shape[1]} cols)", flush=True)


def build_epic_v2_annotation(manifest_path: Path, out_path: Path):
    tag = "epic_v2"
    print(f"[{tag}] parsing {manifest_path}", flush=True)

    with open(manifest_path) as fh:
        sections = find_section_lines(fh)
    if "Assay" not in sections or "Controls" not in sections:
        print(f"[{tag}][error] [Assay] / [Controls] markers not found", file=sys.stderr)
        sys.exit(1)
    assay_marker = sections["Assay"]
    ctrl_marker  = sections["Controls"]
    print(f"[{tag}] [Assay] at line {assay_marker + 1}; [Controls] at line {ctrl_marker + 1}", flush=True)

    assay, ctrl = _read_csv_assay_controls(manifest_path, assay_marker, ctrl_marker)
    print(f"[{tag}] read [Assay]    : {len(assay):,} rows x {assay.shape[1]} cols", flush=True)
    print(f"[{tag}] read [Controls] : {len(ctrl):,} rows x {ctrl.shape[1]} cols (dropped — "
          f"GDC SeSAMe EPIC v2 output does not contain controls)", flush=True)

    # EPIC v2 manifest has IlmnID in col 0 (replicate-suffixed, e.g. cg25324105_BC11)
    # and Name in col 1 (bare CG ID, e.g. cg25324105). GDC's SeSAMe level-3 output
    # uses the bare CG ID, so to make annotation.IlmnID join directly with the data
    # we swap the positions of the first two columns then re-label them so that:
    #   - new col 0 named "IlmnID" -> bare CG ID  (matches data)
    #   - new col 1 named "Name"   -> replicate-suffixed ID (preserved for reference)
    # Done via column reordering (not iloc value-swapping, which can alias under
    # pandas object-block storage). The Controls section is filled positionally
    # below; the swap doesn't affect it.
    new_order = list(assay.columns)
    new_order[0], new_order[1] = new_order[1], new_order[0]
    assay = assay[new_order].copy()
    new_cols = list(assay.columns)
    new_cols[0] = "IlmnID"
    new_cols[1] = "Name"
    assay.columns = new_cols
    print(f"[{tag}] swapped positions of [Assay] cols 0 and 1 and renamed them to "
          f"'IlmnID' (bare CG ID) and 'Name' (replicate-suffixed ID)", flush=True)

    # Controls intentionally NOT appended: GDC SeSAMe EPIC v2 level-3 output
    # contains only assay probes, so any control annotations would be unmatched.
    expanded = _explode_refgene(assay, tag)
    print(f"[{tag}] expanded: {len(assay):,} -> {len(expanded):,} rows "
          f"({len(expanded) - len(assay):,} extra from multi-gene probes)", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    expanded.to_csv(out_path, sep="\t", index=False, na_rep="")
    print(f"[{tag}] wrote {out_path}  ({len(expanded):,} rows x {expanded.shape[1]} cols)", flush=True)


def build_27k_annotation(manifest_path: Path, out_path: Path):
    tag = "27k"
    print(f"[{tag}] parsing {manifest_path}", flush=True)

    # Binary BPM: read whole file as bytes, locate [Heading] byte offset, treat
    # everything from there as text (latin-1 keeps any stray bytes harmless).
    with open(manifest_path, "rb") as fh:
        data = fh.read()
    heading_idx = data.find(b"[Heading]")
    if heading_idx < 0:
        print(f"[{tag}][error] [Heading] marker not found in BPM file", file=sys.stderr)
        sys.exit(1)
    print(f"[{tag}] binary preamble ends at byte {heading_idx} (skipped)", flush=True)
    text = data[heading_idx:].decode("latin-1")

    # Find section line numbers within the text-only portion.
    text_lines = text.splitlines()
    sections = find_section_lines(text_lines)
    if "Assay" not in sections or "Controls" not in sections:
        print(f"[{tag}][error] [Assay] / [Controls] markers not found in CSV body", file=sys.stderr)
        sys.exit(1)
    assay_marker = sections["Assay"]
    ctrl_marker  = sections["Controls"]
    print(f"[{tag}] within CSV body: [Heading] line 1, [Assay] line {assay_marker + 1}, "
          f"[Controls] line {ctrl_marker + 1}", flush=True)

    buf = io.StringIO(text)
    assay, ctrl = _read_csv_assay_controls(buf, assay_marker, ctrl_marker)
    print(f"[{tag}] read [Assay]    : {len(assay):,} rows x {assay.shape[1]} cols", flush=True)
    print(f"[{tag}] read [Controls] : {len(ctrl):,} rows x {ctrl.shape[1]} cols (dropped — "
          f"GDC SeSAMe 27K output does not contain controls)", flush=True)

    # The HM27 manifest [Assay] header ends with trailing commas, so pandas
    # reads two extra empty columns named "Unnamed: 33" and "Unnamed: 34".
    # Drop them — they're pure CSV-format artifacts, never carry data.
    unnamed = [c for c in assay.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        assay = assay.drop(columns=unnamed)
        print(f"[{tag}] dropped {len(unnamed)} empty trailing column(s): {unnamed}", flush=True)

    # Strip "GeneID:" prefix from Gene_ID column.
    if "Gene_ID" in assay.columns:
        before_nonempty = (assay["Gene_ID"].astype(str).str.len() > 0).sum()
        assay["Gene_ID"] = assay["Gene_ID"].fillna("").astype(str).str.replace(r"^GeneID:", "", regex=True)
        print(f"[{tag}] cleaned 'GeneID:' prefix in Gene_ID column "
              f"({before_nonempty:,} non-empty rows affected)", flush=True)
    else:
        print(f"[{tag}][warn] Gene_ID column not found; skipping GeneID: cleanup", flush=True)

    # Add TSS_group column immediately AFTER Distance_to_TSS.
    if "Distance_to_TSS" not in assay.columns:
        print(f"[{tag}][warn] Distance_to_TSS column not found; skipping TSS_group creation", flush=True)
    else:
        tss_groups = assay["Distance_to_TSS"].apply(_tss_group)
        assay.insert(list(assay.columns).index("Distance_to_TSS") + 1, "TSS_group", tss_groups)
        from collections import Counter
        breakdown = Counter(tss_groups)
        print(f"[{tag}] inserted TSS_group column; distribution: "
              f"TSS200={breakdown.get('TSS200', 0):,}, "
              f"TSS1500={breakdown.get('TSS1500', 0):,}, "
              f"empty={breakdown.get('', 0):,}", flush=True)

    # Controls intentionally NOT appended: GDC SeSAMe 27K level-3 output
    # contains only assay probes, so any control annotations would be unmatched.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assay.to_csv(out_path, sep="\t", index=False, na_rep="")
    print(f"[{tag}] wrote {out_path}  ({len(assay):,} rows x {assay.shape[1]} cols)", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

BUILDERS = {
    "450k":    build_450k_annotation,
    "27k":     build_27k_annotation,
    "epic_v2": build_epic_v2_annotation,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--array", nargs="+", default=["all"], metavar="ARRAY",
        help='Which platform(s) to build: any of {"450k","27k","epic_v2","all"}. '
             'Default: all.',
    )
    ap.add_argument(
        "--annotation-dir",
        default=str(Path(__file__).resolve().parent.parent / "data" / "_assembled" / "annotation"),
        help="Directory containing the source manifest files; outputs are also written here.",
    )
    args = ap.parse_args()

    arrays = set(args.array)
    if "all" in arrays:
        arrays = set(PLATFORM_ORDER)
    bad = arrays - set(PLATFORM_ORDER)
    if bad:
        print(f"[error] unknown array(s): {sorted(bad)}; allowed: {PLATFORM_ORDER + ['all']}",
              file=sys.stderr)
        sys.exit(2)

    ann_dir = Path(args.annotation_dir)
    if not ann_dir.is_dir():
        print(f"[error] annotation dir does not exist: {ann_dir}", file=sys.stderr)
        sys.exit(1)

    for p in PLATFORM_ORDER:
        if p not in arrays:
            continue
        manifest = ann_dir / PLATFORMS[p]["manifest"]
        output   = ann_dir / PLATFORMS[p]["output"]
        if not manifest.exists():
            print(f"[{p}][error] manifest not found: {manifest}", file=sys.stderr)
            continue
        BUILDERS[p](manifest, output)
        print()


if __name__ == "__main__":
    main()
