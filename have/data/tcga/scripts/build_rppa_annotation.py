#!/usr/bin/env python3
"""
Build a tab-delimited RPPA antibody -> gene annotation file.

Sources, in priority order (first match wins for each TCGA antibody):
  1. MDA RPPA Core Resources HTML, Table 0 (current full validation list)
     -> parsed from <annotation-dir>/mda_rppa_resources.html
  2. MDA RPPA Core Resources HTML, Table 1 (legacy validation list)
  3. TCPA antibody JSON
     -> parsed from <annotation-dir>/tcpa_annotation-antibody.json

MDA's HTML tables render multi-gene antibodies with `rowspan`: the lead <tr>
holds antibody-level cells (Internal Ab ID, Catalog, Validation, etc.) with
`rowspan="N"` plus the FIRST gene's per-gene cells (Gene Name, Entrez ID,
UniProt). Each additional gene is a follow-on <tr> carrying only those 3
per-gene cells. The parser groups each lead row with its sub-rows and treats
each (antibody, gene) pair as one record. This captures the full multi-gene
panel that the rendered MDA page shows (e.g. ACC1 -> ACACA + ACACB,
Akt -> AKT1 + AKT2 + AKT3).

Match keys per source, tried in order: lab_id -> catalog_number ->
peptide_target -> normalized name. For TCPA only, the TCGA catalog is also
split on `/` and `,` and each piece is tried against TCPA's catalog index.

Output: one row per (peptide_target, gene_symbol) pair. Antibodies that don't
match any source are emitted with empty gene columns. Antibodies that match a
multi-gene source emit one row per gene.

Output columns:
  peptide_target, AGID, lab_id, catalog_number,
  gene_symbol, entrez_gene_id, uniprot_id, rrid,
  validation_status, vendor, species, protein_name_official,
  annotation_source
"""

import argparse
import html as html_lib
import json
import re
import sys
from pathlib import Path

import pandas as pd


OUT_COLS = [
    "peptide_target", "AGID", "lab_id", "catalog_number",
    "gene_symbol", "entrez_gene_id", "uniprot_id", "rrid",
    "validation_status", "vendor", "species", "protein_name_official",
    "annotation_source",
]

EMPTY_ANN_FIELDS = [
    "uniprot_id", "rrid",
    "validation_status", "vendor", "species", "protein_name_official",
]


def norm(s):
    """Normalize an antibody name: strip non-alphanum, uppercase."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def split_multi(s):
    """Split a multi-value string on common separators."""
    if not s:
        return []
    return [p.strip() for p in re.split(r"[,;/\s]+", s) if p.strip()]


def expand_t1_gene_field(s):
    """Expand MDA Table 1's compact multi-gene encoding.

    Table 1 packs all genes targeted by one antibody into a single cell, with
    `, ` as separator. When subsequent genes share a prefix with the first and
    only differ in the trailing letter or digit(s), only the differing suffix is
    written. Examples:

        "ACACA, B"            -> ["ACACA", "ACACB"]
        "AKT1, 2, 3"          -> ["AKT1", "AKT2", "AKT3"]
        "MAPK1, 3"            -> ["MAPK1", "MAPK3"]
        "RPS6KA1, 2, 3"       -> ["RPS6KA1", "RPS6KA2", "RPS6KA3"]
        "PRKCA, B, D, E, H, Q" -> ["PRKCA","PRKCB","PRKCD","PRKCE","PRKCH","PRKCQ"]
        "GSK3A, B"            -> ["GSK3A", "GSK3B"]
        "TUBA4A, TUBA3C"      -> ["TUBA4A", "TUBA3C"]   (both written in full)
        "SRC, YES1, FYN, FGR" -> ["SRC", "YES1", "FYN", "FGR"]  (all standalone)

    Disambiguation rule: a comma-separated token is a SUFFIX (to be appended to
    the first gene's stem) only if it is a single uppercase letter OR a string
    of digits only. Anything else is treated as a full gene name.
    """
    if not s:
        return []
    tokens = [t.strip() for t in s.split(",")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    first = tokens[0]
    out = [first]
    for tok in tokens[1:]:
        if re.fullmatch(r"[A-Z]", tok):
            # Single-letter suffix: replace the trailing letter of `first`
            stem = first[:-1] if first else ""
            out.append(stem + tok)
        elif re.fullmatch(r"\d+", tok):
            # Numeric suffix: replace the trailing run of digits of `first`
            stem = re.sub(r"\d+$", "", first)
            out.append(stem + tok)
        else:
            # Full gene name written out in this position
            out.append(tok)
    return out


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _parse_cells(tbl):
    """Return raw rows-of-cells from one HTML table block, with markup stripped."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.DOTALL)
    out = []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.DOTALL)
        if not cells:
            continue
        clean = []
        for c in cells:
            txt = re.sub(r"<[^>]+>", " ", c)         # strip tags
            txt = html_lib.unescape(txt)             # decode &nbsp;, &amp;, etc.
            txt = txt.replace("\xa0", " ")           # any remaining NBSP -> space
            txt = re.sub(r"\s+", " ", txt).strip()   # collapse whitespace
            clean.append(txt)
        out.append(clean)
    return out


def _group_rowspans(rows):
    """Group lead rows with their per-gene sub-rows.

    A lead row starts a new antibody — its first cell is a digit (the row-
    number 1..N). A sub-row has only the per-gene cells (Gene Name, Entrez,
    UniProt) because the antibody-level cells were merged via rowspan.

    Returns a list of dicts: {'lead': <full lead-row cells>, 'subs': [<sub-row cells>, ...]}.
    """
    groups = []
    current = None
    for r in rows[1:]:    # skip <th> header row
        if not r:
            continue
        if r[0].isdigit():
            if current is not None:
                groups.append(current)
            current = {"lead": r, "subs": []}
        else:
            if current is None:
                continue   # stray sub-row before any lead (shouldn't happen)
            current["subs"].append(r)
    if current is not None:
        groups.append(current)
    return groups


def parse_mda_tables(html_path):
    """Parse MDA RPPA Core Resources HTML and return (t0_groups, t1_groups)."""
    html = html_path.read_text()
    tables = re.findall(r"<table[^>]*>(.*?)</table>", html, flags=re.DOTALL)
    if len(tables) < 2:
        sys.exit(f"[error] expected >= 2 <table> blocks in {html_path}; found {len(tables)}")
    g0 = _group_rowspans(_parse_cells(tables[0]))
    g1 = _group_rowspans(_parse_cells(tables[1]))
    return g0, g1


# ---------------------------------------------------------------------------
# Per-source -> standardized annotation dict
# ---------------------------------------------------------------------------
# Table 0 (lead row has up to 14 cells):
#   0=# 1=Core Ab Name 2=Dataset Name 3=Gene Name 4=Entrez ID 5=Company
#   6=Catalog 7=Internal Ab ID 8=RRID 9=Species 10=Validation 11=Dilution
#   12=Storage 13=UniProt
# Sub-rows have 3 cells: [Gene Name, Entrez ID, UniProt]
#
# Table 1 (lead row has up to 11 cells; no Entrez/RRID/UniProt cols):
#   0=# 1=Official Ab Name 2=Dataset Name 3=Gene Name 4=Company 5=Catalog
#   6=Internal Ab ID 7=Species 8=Validation 9=Dilution 10=Storage
# Sub-rows have 1 cell: [Gene Name]   (T1 rarely uses rowspans; handled anyway)

def t0_group_to_ann(group):
    """Map a Table-0 group to standardized antibody annotation dict + per-gene tuples."""
    lead = group["lead"]
    g = lambda i: lead[i] if len(lead) > i else ""
    base = {
        "vendor":                g(5),
        "rrid":                  g(8),
        "species":               g(9),
        "validation_status":     g(10),
        "protein_name_official": g(1),
    }
    # First per-gene tuple from the lead row
    per_gene = [(g(3), g(4), g(13))]
    # Additional per-gene tuples from sub-rows (3 cells each: gene, entrez, uniprot)
    for sub in group["subs"]:
        gene  = sub[0] if len(sub) > 0 else ""
        ez    = sub[1] if len(sub) > 1 else ""
        upid  = sub[2] if len(sub) > 2 else ""
        per_gene.append((gene, ez, upid))
    return base, per_gene


def t1_group_to_ann(group):
    """Map a Table-1 group to standardized antibody annotation dict + per-gene tuples.

    Table 1 encodes multi-gene antibodies as comma-separated tokens in a single
    Gene Name cell, with later genes abbreviated to just their differing suffix.
    Decoded via `expand_t1_gene_field`. Table 1 has no Entrez / UniProt columns.
    """
    lead = group["lead"]
    g = lambda i: lead[i] if len(lead) > i else ""
    base = {
        "vendor":                g(4),
        "rrid":                  "",
        "species":               g(7),
        "validation_status":     g(8),
        "protein_name_official": g(1),
    }
    genes = expand_t1_gene_field(g(3))
    if not genes:
        per_gene = [("", "", "")]
    else:
        per_gene = [(gene, "", "") for gene in genes]
    # Also include any sub-rows that might exist (defensive — Table 1 doesn't use rowspans in practice)
    for sub in group["subs"]:
        gene = sub[0] if len(sub) > 0 else ""
        if gene:
            per_gene.append((gene, "", ""))
    return base, per_gene


def tcpa_to_ann(ab):
    """Map a TCPA antibody record to standardized antibody annotation dict +
    per-gene tuples (TCPA stores all genes as a comma-separated string)."""
    base = {
        "vendor":                ab.get("source", ""),
        "rrid":                  ab.get("rrid", ""),
        "species":               ab.get("origin", ""),
        "validation_status":     ab.get("validation_status", ""),
        "protein_name_official": ab.get("protein_name", ""),
    }
    genes = split_multi(ab.get("genes", ""))
    per_gene = [(g, "", "") for g in genes] if genes else [("", "", "")]
    return base, per_gene


# ---------------------------------------------------------------------------
# Indexing helpers
# ---------------------------------------------------------------------------

def t0_indexes(groups):
    by_labid, by_cat, by_name, by_norm = {}, {}, {}, {}
    for grp in groups:
        lead = grp["lead"]
        if len(lead) > 7 and lead[7]: by_labid.setdefault(lead[7], grp)
        if len(lead) > 6 and lead[6]: by_cat.setdefault(lead[6], grp)
        if len(lead) > 2 and lead[2]:
            by_name.setdefault(lead[2], grp)
            by_norm.setdefault(norm(lead[2]), grp)
    return by_labid, by_cat, by_name, by_norm


def t1_indexes(groups):
    by_labid, by_cat, by_name, by_norm = {}, {}, {}, {}
    for grp in groups:
        lead = grp["lead"]
        if len(lead) > 6 and lead[6]: by_labid.setdefault(lead[6], grp)
        if len(lead) > 5 and lead[5]: by_cat.setdefault(lead[5], grp)
        if len(lead) > 2 and lead[2]:
            by_name.setdefault(lead[2], grp)
            by_norm.setdefault(norm(lead[2]), grp)
    return by_labid, by_cat, by_name, by_norm


def tcpa_indexes(tcpa_abs):
    by_cat  = {ab["catalog_number"]: ab for ab in tcpa_abs if ab.get("catalog_number")}
    by_name = {ab["protein_name"]: ab   for ab in tcpa_abs if ab.get("protein_name")}
    by_norm = {norm(ab["protein_name"]): ab for ab in tcpa_abs if ab.get("protein_name")}
    return by_cat, by_name, by_norm


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tcga-root",
                    default=str(Path(__file__).resolve().parent.parent / "data"),
                    help="Root containing TCGA-<PROJECT>/ folders.")
    ap.add_argument("--annotation-dir",
                    default=str(Path(__file__).resolve().parent.parent / "data" / "_assembled" / "annotation"),
                    help="Directory with the MDA HTML + TCPA JSON; output also written here.")
    ap.add_argument("--output",
                    default=str(Path(__file__).resolve().parent.parent / "data" / "_assembled" / "annotation" / "rppa.annotation.txt"),
                    help="Path for the tab-delimited annotation output.")
    args = ap.parse_args()

    tcga_root = Path(args.tcga_root)
    ann_dir   = Path(args.annotation_dir)
    out_path  = Path(args.output)

    # ---- 1. TCGA antibodies (panel is uniform across all 7,906 files) ----
    tcga_abs = {}     # peptide_target -> (AGID, lab_id, catalog_number)
    n_proj = 0
    for proj in sorted(tcga_root.glob("TCGA-*")):
        rdir = proj / "Proteome_Profiling" / "Protein_Expression_Quantification"
        if not rdir.is_dir(): continue
        files = sorted(rdir.rglob("*_RPPA_data.tsv"))
        if not files: continue
        n_proj += 1
        with open(files[0]) as fh:
            h = next(fh).rstrip().split("\t")
            ia, il, ic, it = h.index("AGID"), h.index("lab_id"), h.index("catalog_number"), h.index("peptide_target")
            for line in fh:
                p = line.rstrip().split("\t")
                tcga_abs.setdefault(p[it], (p[ia], p[il], p[ic]))
    print(f"[tcga] {n_proj} project sample files scanned -> {len(tcga_abs):,} unique antibodies", flush=True)

    # ---- 2. Annotation sources ----
    mda_html  = ann_dir / "mda_rppa_resources.html"
    tcpa_json = ann_dir / "tcpa_annotation-antibody.json"
    for p in (mda_html, tcpa_json):
        if not p.exists():
            sys.exit(f"[error] missing annotation source: {p}")

    t0_groups, t1_groups = parse_mda_tables(mda_html)
    # Table 0 uses rowspans -> multi-gene == has sub-rows
    t0_multigene = sum(1 for g in t0_groups if len(g["subs"]) > 0)
    # Table 1 uses comma-encoded multi-gene in the Gene Name cell
    t1_multigene = sum(
        1 for g in t1_groups
        if len(g["lead"]) > 3 and len(expand_t1_gene_field(g["lead"][3])) > 1
    )
    print(f"[mda] Table 0: {len(t0_groups)} antibodies "
          f"({t0_multigene} multi-gene, via rowspans)", flush=True)
    print(f"[mda] Table 1: {len(t1_groups)} antibodies "
          f"({t1_multigene} multi-gene, via comma-encoded gene field)", flush=True)

    t0_by_labid, t0_by_cat, t0_by_name, t0_by_norm = t0_indexes(t0_groups)
    t1_by_labid, t1_by_cat, t1_by_name, t1_by_norm = t1_indexes(t1_groups)

    tcpa_abs = json.load(open(tcpa_json))["antibodies"]
    tcpa_by_cat, tcpa_by_name, tcpa_by_norm = tcpa_indexes(tcpa_abs)
    print(f"[tcpa] {len(tcpa_abs)} antibodies", flush=True)

    # ---- 3. Priority match each TCGA antibody, then emit per-gene rows ----
    out_rows = []
    src_counts = {}

    for tgt, (agid, lid, cat) in sorted(tcga_abs.items()):
        base_ann, per_gene, src = None, None, None

        if   lid in t0_by_labid:        base_ann, per_gene = t0_group_to_ann(t0_by_labid[lid]);          src = "MDA_T0_labid"
        elif cat in t0_by_cat:          base_ann, per_gene = t0_group_to_ann(t0_by_cat[cat]);            src = "MDA_T0_catalog"
        elif tgt in t0_by_name:         base_ann, per_gene = t0_group_to_ann(t0_by_name[tgt]);           src = "MDA_T0_name"
        elif norm(tgt) in t0_by_norm:   base_ann, per_gene = t0_group_to_ann(t0_by_norm[norm(tgt)]);     src = "MDA_T0_norm"
        elif lid in t1_by_labid:        base_ann, per_gene = t1_group_to_ann(t1_by_labid[lid]);          src = "MDA_T1_labid"
        elif cat in t1_by_cat:          base_ann, per_gene = t1_group_to_ann(t1_by_cat[cat]);            src = "MDA_T1_catalog"
        elif tgt in t1_by_name:         base_ann, per_gene = t1_group_to_ann(t1_by_name[tgt]);           src = "MDA_T1_name"
        elif norm(tgt) in t1_by_norm:   base_ann, per_gene = t1_group_to_ann(t1_by_norm[norm(tgt)]);     src = "MDA_T1_norm"
        elif cat in tcpa_by_cat:        base_ann, per_gene = tcpa_to_ann(tcpa_by_cat[cat]);              src = "TCPA_catalog"
        else:
            tcpa_hit = None
            for part in re.split(r"[/,]", cat or ""):
                p = part.strip()
                if p and p in tcpa_by_cat:
                    tcpa_hit = tcpa_by_cat[p]; break
            if tcpa_hit is not None:                base_ann, per_gene = tcpa_to_ann(tcpa_hit);                  src = "TCPA_catalog_split"
            elif tgt in tcpa_by_name:               base_ann, per_gene = tcpa_to_ann(tcpa_by_name[tgt]);         src = "TCPA_name"
            elif norm(tgt) in tcpa_by_norm:         base_ann, per_gene = tcpa_to_ann(tcpa_by_norm[norm(tgt)]);   src = "TCPA_norm"
            else:                                   base_ann, per_gene = None, None;                              src = "UNMATCHED"

        src_counts[src] = src_counts.get(src, 0) + 1

        tcga_part = {
            "peptide_target": tgt,
            "AGID": agid,
            "lab_id": lid,
            "catalog_number": cat,
            "annotation_source": src,
        }

        if base_ann is None:
            # Unmatched antibody: single output row with empty gene info
            row = dict(tcga_part)
            for c in EMPTY_ANN_FIELDS:
                row[c] = ""
            row["gene_symbol"] = ""
            row["entrez_gene_id"] = ""
            out_rows.append(row)
        else:
            for (gene, ez, upid) in per_gene:
                row = dict(tcga_part)
                row.update(base_ann)
                row["gene_symbol"] = gene
                row["entrez_gene_id"] = ez
                row["uniprot_id"] = upid
                out_rows.append(row)

    df = pd.DataFrame(out_rows)
    df = df[OUT_COLS]

    n_total = len(tcga_abs)
    n_matched = sum(v for k, v in src_counts.items() if k != "UNMATCHED")
    print(f"\n[match] priority-chain match counts:")
    for src in [
        "MDA_T0_labid", "MDA_T0_catalog", "MDA_T0_name", "MDA_T0_norm",
        "MDA_T1_labid", "MDA_T1_catalog", "MDA_T1_name", "MDA_T1_norm",
        "TCPA_catalog", "TCPA_catalog_split", "TCPA_name", "TCPA_norm",
        "UNMATCHED",
    ]:
        if src in src_counts:
            print(f"  {src:>22}: {src_counts[src]:>3}")
    print(f"  {'TOTAL MATCHED':>22}: {n_matched:>3} / {n_total} ({100*n_matched/n_total:.1f}%)")
    print(f"\n[explode] {n_total:,} antibodies -> {len(df):,} output rows "
          f"({len(df) - n_total:,} extra from multi-gene)", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, sep="\t", index=False, na_rep="")
    print(f"\n[write] {out_path} ({len(df):,} rows x {df.shape[1]} cols)", flush=True)


if __name__ == "__main__":
    main()
