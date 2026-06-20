# TCGA Data Downloading and Processing

End-to-end pipeline that (1) downloads every publicly-available data modality for each of the 33 TCGA cancer cohorts via the GDC, (2) assembles per-data-type pan-cancer matrices and metadata tables, (3) builds probe/antibody annotations, and (4) optionally converts the large assembled TSVs to compressed Parquet for fast downstream analysis.

All work lives under `have/data/tcga/`.

---

## 1. Top-level layout

```
have/data/tcga/
├── README.md              ← this file
├── scripts/               ← all code
│   ├── tcga_extractor_agent.py     ← LLM-driven per-project downloader (R/TCGAbiolinks under the hood)
│   ├── tcga_gdc_client_agent.py    ← alternative LLM-driven downloader (GDC API + gdc-client; no R)
│   ├── tcga_helpers.R              ← R helper called from the extractor agent (GDCquery + GDCdownload)
│   ├── download_all_tcga.sh        ← bulk-runs the extractor agent over all 33 projects
│   ├── gdc-client                  ← Genomic Data Commons Data Transfer Tool (binary, used by both agents)
│   ├── assemble_cnv_ascat3.py      ← pan-cancer matrix: gene-level copy number (ASCAT3)
│   ├── assemble_ge_star_tpm.py     ← pan-cancer matrix: gene expression (STAR / TPM)
│   ├── assemble_mirna_bcgsc.py     ← pan-cancer matrix: miRNA expression (BCGSC)
│   ├── assemble_dnam_sesame.py     ← pan-cancer matrices: methylation β-values (27K / 450K / EPIC v2)
│   ├── assemble_rppa.py            ← pan-cancer matrix: RPPA protein expression
│   ├── assemble_mutation_maf.py    ← pan-cancer mutation table + mutation/gene-by-case matrices
│   ├── build_dnam_annotation.py    ← probe-level annotation for methylation arrays
│   ├── build_rppa_annotation.py    ← antibody-to-gene annotation for RPPA
│   ├── convert_to_parquet.py       ← TSV → Parquet (ZSTD) for any of the assembled matrices
│   └── logs/                       ← per-project download logs + per-assembly logs
│       └── TCGA-<PROJECT>.log, assemble_*.log, convert_*.log
└── data/                  ← downloaded data + assembled outputs
    ├── TCGA-ACC/, TCGA-BLCA/, ..., TCGA-UVM/   ← 33 per-project folders (raw downloads)
    └── _assembled/                              ← pan-cancer outputs from assemble_*.py
        ├── annotation/                          ← probe/antibody annotations (long-lived reference data)
        └── *.txt, *.parquet                     ← assembled matrices + metadata tables
```

All scripts use **script-relative defaults**: running `assemble_*.py` or `tcga_extractor_agent.py` from any working directory writes/reads to `have/data/tcga/data/...`. Override via `--tcga-root` / `--out-dir` / env vars when needed.

Most scripts run inside the `biomni_e1` conda env (which provides pandas, pyarrow, openai, R + TCGAbiolinks). Standard invocation:

```bash
conda run -n biomni_e1 --no-capture-output python <script.py> [args...]
```

---

## 2. Per-project data layout (under `data/TCGA-<PROJECT>/`)

After the extractor agent has finished a project, the layout is:

```
data/TCGA-CHOL/
├── Biospecimen/
│   └── Biospecimen_Supplement/<file_uuid>/<sample.xml or .biotab>
├── Clinical/
│   ├── Clinical_Supplement/<file_uuid>/<sample.xml>
│   └── Pathology_Report/<file_uuid>/<TCGA-XX-YYYY.<id>.PDF>
├── Copy_Number_Variation/
│   ├── Allele-specific_Copy_Number_Segment/  ← three workflow subfolders: ASCAT2 / ASCAT3 / AscatNGS
│   ├── Copy_Number_Segment/                  ← workflows: DNAcopy, GATK4 CNV
│   ├── Gene_Level_Copy_Number/               ← workflows: ASCAT2, ASCAT3, AscatNGS, ABSOLUTE LiftOver
│   ├── Masked_Copy_Number_Segment/           ← workflow: DNAcopy (germline-masked)
│   └── <WorkflowName>.manifest.tsv           ← per-workflow file manifest (one row per file)
├── DNA_Methylation/
│   └── Methylation_Beta_Value/               ← SeSAMe β-value TXT files (450K or EPIC v2 or 27K)
├── Proteome_Profiling/
│   └── Protein_Expression_Quantification/    ← RPPA TSVs (~200 antibodies × samples; workflow "n/a")
├── Simple_Nucleotide_Variation/
│   └── Masked_Somatic_Mutation/              ← .maf.gz (+ decompressed .maf alongside)
├── Transcriptome_Profiling/
│   ├── Gene_Expression_Quantification/       ← STAR Counts (`*.rna_seq.augmented_star_gene_counts.tsv`)
│   ├── Isoform_Expression_Quantification/    ← BCGSC miRNA isoform counts
│   └── miRNA_Expression_Quantification/      ← BCGSC mature miRNA counts
├── file_manifest.tsv                         ← union of all per-workflow manifests (project-level rollup)
├── patient_files.tsv                         ← patient_id × modality → list of file UUIDs (pivot)
├── modalities_cache.json                     ← cached output of `list_tcga_public_data_types`
├── schema_summary.md                         ← agent's per-modality schema notes
└── size_summary.md                           ← per-modality file count + size rollup
```

### Per-workflow manifest (`<Workflow>.manifest.tsv`) columns

| Column | Meaning |
|---|---|
| `file_id` | GDC file UUID (also the subdirectory name on disk) |
| `file_name` | original GDC filename (matches the file inside `<file_id>/`) |
| `patient_id` | TCGA patient barcode (3 parts, e.g. `TCGA-W5-AA39`) |
| `sample_barcode` | tumor aliquot barcode (7 parts) for single-aliquot files, OR `tumor;normal` semicolon-pair for paired analyses (CN, mutations) |
| `cases` | full list of aliquot barcodes referenced by the file (comma- or semicolon-separated) |
| `project` | `TCGA-<PROJECT>` |
| `data_category` / `data_type` / `workflow_type` | GDC's three-level classification |
| `data_format` | e.g. `TXT`, `MAF`, `BPM`, `IDAT` |
| `file_size` | bytes |
| `md5sum` | checksum |
| `access` | `open` (everything we download) |

### Per-project rollup files

| File | What it is |
|---|---|
| `file_manifest.tsv` | Union of every per-workflow manifest under this project. Same schema as above. |
| `patient_files.tsv` | Wide pivot: one row per `patient_id`, one column per `<data_category> / <data_type> / <workflow>` triple. Cell = comma-joined list of file UUIDs that patient has in that modality. |
| `modalities_cache.json` | Caches what `list_tcga_public_data_types` returned (so re-running the agent doesn't re-hit the GDC). Keys: `project`, `case_count`, `n_modalities`, `modalities` (each with `data_category`, `data_type`, `workflow_type`, `data_formats`, `n_files`). |
| `schema_summary.md` | LLM-generated narrative notes on what each modality looks like in this cohort. |
| `size_summary.md` | Ranked table: per-modality file count, average + total file size, unique patient count, short description. |

---

## 3. The 8 downloaded data modalities (after applying default `TCGA_EXCLUDE_DATA_TYPES=Slide Image,Masked Intensities`)

| Data category | Data type | Workflow | What's in each file |
|---|---|---|---|
| **Copy Number Variation** | Allele-specific Copy Number Segment | ASCAT2, ASCAT3, AscatNGS | per-segment major/minor allele CN |
| | Copy Number Segment | DNAcopy, GATK4 CNV | per-segment total CN log2 ratio |
| | Gene Level Copy Number | ASCAT2, ASCAT3, AscatNGS, ABSOLUTE LiftOver | per-gene integer CN |
| | Masked Copy Number Segment | DNAcopy | same as Copy Number Segment, germline-CNV regions masked |
| **DNA Methylation** | Methylation Beta Value | SeSAMe Methylation Beta Estimation | per-CpG β-values (0–1); one of three array platforms per file (27K / 450K / EPIC v2 — auto-detected by size) |
| **Transcriptome Profiling** | Gene Expression Quantification | STAR - Counts | per-gene reads / TPM / FPKM (one row per Ensembl gene) |
| | miRNA Expression Quantification | BCGSC miRNA Profiling | per-mature-miRNA read counts + RPM |
| | Isoform Expression Quantification | BCGSC miRNA Profiling | per-miRNA-isoform counts (mature + star strands) |
| **Proteome Profiling** | Protein Expression Quantification | n/a (MD Anderson RPPA Core) | per-antibody protein abundance |
| **Simple Nucleotide Variation** | Masked Somatic Mutation | Aliquot Ensemble Somatic Variant Merging and Masking | one MAF per tumor aliquot, ensemble of ~5 callers, germline-masked |
| **Clinical** | Clinical Supplement | n/a | XML + Biotab with demographics, stage, treatment, survival |
| | Pathology Report | n/a | scanned PDFs |
| **Biospecimen** | Biospecimen Supplement | n/a | XML/Biotab with aliquot/portion/sample metadata |

Two large modalities are **excluded by default** to save disk:
- `Slide Image` (whole-slide histology SVS files; ~800 GB per cancer)
- `Masked Intensities` (raw methylation IDAT files; ~14 GB per cancer)

To include them, set e.g. `TCGA_EXCLUDE_DATA_TYPES=""` (include all) or `TCGA_EXCLUDE_DATA_TYPES="Slide Image"` (exclude only one).

---

## 4. Scripts

### 4.1 Data download

#### `tcga_extractor_agent.py`

LLM-driven agent (Argo Gateway / gpt54) that, for one TCGA project at a time, queries every public data category, lists every modality (`data_category × data_type × workflow_type`), and uses **TCGAbiolinks** (via a small R helper) to download every file of each non-excluded modality.

Output layout: matches TCGAbiolinks native structure — `<TCGA_OUTPUT_ROOT>/<PROJECT>/<data_category>/<data_type>/<file_uuid>/<file>`.

**Env vars (all optional):**

| Var | Default | Meaning |
|---|---|---|
| `TCGA_PROJECT` | `TCGA-LUAD` | which project to download |
| `TCGA_OUTPUT_ROOT` | `have/data/tcga/data` | output root |
| `TCGA_MAX_FILES` | `5` | per-modality file cap (use `0` or `unlimited` to disable) |
| `TCGA_MAX_MODALITIES` | unlimited | cap on number of modalities to profile |
| `TCGA_EXCLUDE_DATA_TYPES` | `Slide Image` | comma-separated `data_type` names to skip |
| `ARGO_USER`, `ARGO_MODEL` | `yitan.zhu`, `gpt54` | Argo Gateway credentials |

**Run one project (feasibility test, capped at 5 files/modality):**

```bash
TCGA_PROJECT=TCGA-CHOL conda run -n biomni_e1 --no-capture-output \
  python -u have/data/tcga/scripts/tcga_extractor_agent.py
```

**Run one project (full download, both elephant modalities excluded):**

```bash
TCGA_PROJECT=TCGA-CHOL \
TCGA_MAX_FILES=0 \
TCGA_EXCLUDE_DATA_TYPES="Slide Image,Masked Intensities" \
conda run -n biomni_e1 --no-capture-output \
  python -u have/data/tcga/scripts/tcga_extractor_agent.py
```

#### `tcga_helpers.R`

Internal R helper called by `tcga_extractor_agent.py`. Dispatches on an `action` field in a JSON request file and writes the result to a `response_path`. Actions:

- `list_public_data_types(project)` — runs `getProjectSummary` + per-category `GDCquery` to enumerate every modality
- `download_modality(project, data_category, data_type, workflow_type, output_root)` — runs `GDCquery` + `GDCdownload` + (best-effort) `GDCprepare`
- `extract_schema(file_path)` — opens one downloaded file and returns a structural description

Not called directly by users.

#### `download_all_tcga.sh`

Wrapper that runs `tcga_extractor_agent.py` for every TCGA project (or a subset), sequentially. Each project's log lands at `have/data/tcga/scripts/logs/TCGA-<PROJECT>.log`. The script defaults to `TCGA_EXCLUDE_DATA_TYPES="Slide Image,Masked Intensities"` and `TCGA_MAX_FILES=0` (everything).

**All 33 projects, full download (~3.5 days):**

```bash
bash have/data/tcga/scripts/download_all_tcga.sh
```

**Subset:**

```bash
bash have/data/tcga/scripts/download_all_tcga.sh TCGA-BRCA TCGA-OV TCGA-LUAD
```

#### `tcga_gdc_client_agent.py`

Alternative LLM-driven downloader. Instead of TCGAbiolinks (R) it uses GDC's REST API directly + the `gdc-client` binary for the actual downloads. Useful when:

- TCGAbiolinks' `GDCquery` times out on huge cohorts (BRCA SNV had ~21,000 files in one query and timed out)
- You want a `<CANCER_TYPE>/<data_category>/<data_type>/<file_uuid>/<file>` layout
- You don't have R + TCGAbiolinks set up

Writes to `have/data/tcga/data/_gdc_client/` (separate from the main extractor's output) so the two don't collide.

**Env vars:** see the docstring at the top of the script. Key ones include `TCGA_PROJECT`, `DOWNLOAD_ALL_SAMPLES`, `TCGA_GDC_OUTPUT_ROOT`, `TCGA_GDC_MAX_CASES`, `TCGA_GDC_EXCLUDE`.

```bash
TCGA_PROJECT=TCGA-CHOL conda run -n biomni_e1 --no-capture-output \
  python -u have/data/tcga/scripts/tcga_gdc_client_agent.py
```

#### `gdc-client`

GDC Data Transfer Tool binary (v2.3). Used by `tcga_gdc_client_agent.py` and was also used ad-hoc to download BRCA MAFs directly when the agent's GDCquery timed out. Direct usage:

```bash
have/data/tcga/scripts/gdc-client download -m <manifest.tsv> -n 8
```

### 4.2 Assemblers (per-data-type pan-cancer matrices)

All assemblers share the same pattern:
1. Walk `data/TCGA-*/<modality_path>/<workflow>.manifest.tsv` to discover every per-sample file.
2. Read each file, append its data values as a column of the pan-cancer matrix (or as a row for the mutation long-format).
3. Enforce a canonical feature order — if any file's features differ from canonical, reindex and log.
4. Write `<name>.<value_col>.txt` (data matrix) + `<name>.metadata.txt` (one row per file UUID, same 15-column schema).

Common CLI:

```bash
python <assembler.py> [--projects TCGA-CHOL TCGA-BRCA ...] [--tcga-root <dir>] [--out-dir <dir>]
```

Defaults: `--tcga-root = have/data/tcga/data`, `--out-dir = have/data/tcga/data/_assembled`.

| Script | Input modality | Output (matrix) | Output (metadata) | Notes |
|---|---|---|---|---|
| `assemble_cnv_ascat3.py` | Gene Level Copy Number / ASCAT3 | `cnv_ascat3.copy_number.txt` (60,623 genes × 10,632 samples) | `cnv_ascat3.metadata.txt` | Uses only the `copy_number` column (ignores `min_/max_copy_number`). Gene-row consistency checked via (gene_id, gene_name, chromosome, start, end) 5-tuple. |
| `assemble_ge_star_tpm.py` | Gene Expression Quantification / STAR - Counts | `ge_star.tpm_unstranded.txt` (60,660 genes × 11,505 samples) | `ge_star.metadata.txt` | Uses only `tpm_unstranded`. STAR alignment-stats rows (`N_unmapped`, `N_multimapping`, `N_noFeature`, `N_ambiguous`) are dropped. |
| `assemble_mirna_bcgsc.py` | miRNA Expression Quantification / BCGSC miRNA Profiling | `mirna_bcgsc.reads_per_million.txt` (1,881 miRNAs × 11,442 samples) | `mirna_bcgsc.metadata.txt` | Uses only `reads_per_million_miRNA_mapped`. |
| `assemble_dnam_sesame.py` | Methylation Beta Value / SeSAMe (auto-split by array platform) | `dnam_sesame_27k.beta_value.txt` (27,578 × 2,663) + `dnam_sesame_450k.beta_value.txt` (486,427 × 9,812) + `dnam_sesame_epic_v2.beta_value.txt` (930,659 × 53) | `dnam_sesame.metadata.txt` (combined, 16-col with `array_platform`) | Detects HM27 vs HM450 vs EPIC v2 by file size; writes a separate matrix per platform. |
| `assemble_rppa.py` | Protein Expression Quantification (RPPA) | `rppa.protein_expression.txt` (487 antibodies × 7,906 samples) | `rppa.metadata.txt` | Uses only `protein_expression`. Within-cohort an older ~247-antibody panel coexists with the newer 487-antibody panel; 406 files trigger reindex/NA-fill (handled cleanly). |
| `assemble_mutation_maf.py` | Masked Somatic Mutation / Aliquot Ensemble | `mutation.maf.txt` (long format, 2,570,542 rows × 140 cols) + `mutation.mutation_by_case.txt` (binary mutation×case matrix) + `mutation.gene_by_case.txt` (gene×case count matrix) | `mutation.metadata.txt` (17-col, includes `case` and `Tumor_Sample_UUID`) | Also decompresses each `.maf.gz` to a sibling `.maf` file. Normalizes `Tumor_Seq_Allele1 ≥ Tumor_Seq_Allele2` per row (string compare). |

**Examples:**

```bash
# pan-cancer
conda run -n biomni_e1 --no-capture-output \
  python have/data/tcga/scripts/assemble_ge_star_tpm.py \
  > have/data/tcga/scripts/logs/assemble_ge_star_tpm.log 2>&1

# subset for testing
conda run -n biomni_e1 --no-capture-output \
  python have/data/tcga/scripts/assemble_ge_star_tpm.py \
  --projects TCGA-CHOL TCGA-DLBC --out-dir /tmp/ge_smoke
```

### 4.3 Annotation builders

#### `build_dnam_annotation.py`

Builds tab-delimited probe annotations for methylation arrays from Illumina manifest files.

Sources (must exist in `data/_assembled/annotation/`):
- 450K: `humanmethylation450_15017482_v1-2.csv`
- 27K:  `humanmethylation27_270596_v1-2.bpm` (binary BPM with embedded CSV)
- EPIC v2: `EPIC-8v2-0_A2.csv`

Outputs (same dir):
- `dnam_450k.annotation.txt` (807,704 rows × 33 cols)
- `dnam_27k.annotation.txt`  (27,578 rows × 34 cols, with derived `TSS_group` column)
- `dnam_epic_v2.annotation.txt` (1,894,457 rows × 51 cols; col 1 is the bare CG ID so it joins directly to the matrix's `IlmnID`)

```bash
# build all three
python have/data/tcga/scripts/build_dnam_annotation.py

# build a single array
python have/data/tcga/scripts/build_dnam_annotation.py --array 450k
```

#### `build_rppa_annotation.py`

Builds RPPA antibody → gene mapping from two sources (priority order):
1. MDA RPPA Core Resources HTML (rowspan-aware parser; handles multi-gene antibodies)
2. TCPA antibody JSON

Inputs (must exist in `data/_assembled/annotation/`):
- `mda_rppa_resources.html` (the antibody table page from the MDA RPPA Core site)
- `tcpa_annotation-antibody.json` (from `https://tcpa.drbioright.org/rppa500/annotation-antibody`)

Output:
- `rppa.annotation.txt` (545 rows × 13 cols; one row per (peptide_target, gene_symbol) pair)

```bash
python have/data/tcga/scripts/build_rppa_annotation.py
```

### 4.4 Parquet conversion

#### `convert_to_parquet.py`

Converts the assembled TSVs (and any future similarly-shaped matrices) to ZSTD-compressed Parquet. Reads in streaming row-chunks so even the 46 GB `mutation.mutation_by_case.txt` doesn't have to fit in memory.

Two modes:
- **Default (matrix mode)**: assumes the file has one string feature-key column (gene_id, IlmnID, miRNA_ID, peptide_target, etc.) plus N numeric value columns. Uses a hardcoded dtype map for performance.
- **`--infer-dtypes`**: skips the dtype map and uses `pyarrow.csv` to auto-detect per-column types. Needed for files with heterogeneous mixed-type columns (e.g., long-format MAFs).

```bash
# convert every TSV in _assembled/ that isn't a metadata file
python have/data/tcga/scripts/convert_to_parquet.py

# convert specific files
python have/data/tcga/scripts/convert_to_parquet.py \
  --files have/data/tcga/data/_assembled/cnv_ascat3.copy_number.txt

# convert mutation files (mixed types, need --infer-dtypes)
python have/data/tcga/scripts/convert_to_parquet.py \
  --files have/data/tcga/data/_assembled/mutation.maf.txt \
  --infer-dtypes

# dry-run: list what would be converted
python have/data/tcga/scripts/convert_to_parquet.py --dry-run
```

Typical compression ratios on this dataset:

| File | TSV | Parquet | Ratio |
|---|---:|---:|---:|
| `cnv_ascat3.copy_number` | 1.3 GB | 27 MB | **46×** |
| `mirna_bcgsc.reads_per_million` | 118 MB | 30 MB | 4.0× |
| `dnam_sesame_27k.beta_value` | 728 MB | 347 MB | 2.1× |
| `dnam_sesame_epic_v2.beta_value` | 471 MB | 233 MB | 2.0× |
| `dnam_sesame_450k.beta_value` | 43 GB | 21 GB | 2.1× |
| `ge_star.tpm_unstranded` | 3.8 GB | 1.9 GB | 2.0× |
| `rppa.protein_expression` | 34 MB | 24 MB | 1.4× |
| `mutation.maf` | 4.1 GB | 678 MB | 6.1× |
| `mutation.gene_by_case` | 399 MB | 27 MB | 14.8× |
| `mutation.mutation_by_case` | 46 GB | 2.6 GB | 17.7× |

The TSV originals are NOT deleted by the converter — both formats live side-by-side until you remove the TSVs.

---

## 5. Assembled data files (in `data/_assembled/`)

### 5.1 Common metadata schema (15 columns)

Every assembler emits a `<dataset>.metadata.txt` file with one row per `file_uuid` (column 1) and the **same 15 base columns** (DNA methylation adds 1 more, mutations add 2 more):

| # | Column | Source / meaning |
|---:|---|---|
| 1 | `file_uuid` | GDC file UUID; also the data matrix's sample-column header |
| 2 | `file_name` | original filename in GDC |
| 3 | `cancer_type` | `BRCA`, `LUAD`, etc. (no `TCGA-` prefix) |
| 4 | `study_name` | full disease name derived from the TSS code in the sample barcode (e.g., `Breast invasive carcinoma`) |
| 5 | `patient_barcode` | TCGA patient ID (3 parts, e.g., `TCGA-W5-AA39`) |
| 6 | `sample_barcode` | full tumor aliquot barcode (7 parts) |
| 7 | `sample_type` | text from GDC sample-type table (e.g., `Primary Solid Tumor`, `Solid Tissue Normal`, `Metastatic`) |
| 8 | `is_tumor` | derived from the 2-digit sample-type code (01–09 → True) |
| 9 | `is_normal` | derived (10–19 → True) |
| 10 | `is_metastatic` | derived (06, 07 → True) |
| 11 | `matched_normal_barcode` | full barcode of the matched normal aliquot (populated for CN, mutations; NA for GE, miRNA, DNAm, RPPA) |
| 12 | `data_category` | GDC category (e.g., `Copy Number Variation`) |
| 13 | `data_type` | GDC type (e.g., `Gene Level Copy Number`) |
| 14 | `workflow_type` | GDC workflow (e.g., `ASCAT3`) |
| 15 | `md5sum` | from GDC manifest |
| 16 | `array_platform` | **DNA methylation only** — `27K` / `450K` / `EPIC v2` |
| 17 | `case` | **mutations only** — `<tumor_barcode>, <normal_barcode>` (matches `case_id` column header in the mutation-by-case + gene-by-case matrices) |
| 18 | `Tumor_Sample_UUID` | **mutations only** — pulled from the MAF's `#tumor.aliquot` comment line; primary join key into `mutation.maf.txt` |

### 5.2 Wide-format matrices (one column per sample)

For these matrices, **the column header is a `file_uuid`** (or a `case_id` for the mutation matrices) that joins to the corresponding metadata table's `file_uuid` column (or `case` column).

#### `cnv_ascat3.copy_number.txt` — gene-level copy number

- **Shape**: 60,623 genes × (5 gene-info cols + 10,632 sample cols)
- **Gene-info cols** (first 5): `gene_id`, `gene_name`, `chromosome`, `start`, `end`
- **Sample cols**: integer copy-number calls (`Int16`), e.g., 2 = diploid, 0 = homozygous deletion, ≥3 = gain. ASCAT3 reports tumor-purity-corrected absolute integer CN.

#### `ge_star.tpm_unstranded.txt` — gene expression

- **Shape**: 60,660 genes × (3 gene-info cols + 11,505 sample cols)
- **Gene-info cols** (first 3): `gene_id` (Ensembl, with version), `gene_name` (HGNC symbol), `gene_type` (`protein_coding`, `lncRNA`, etc.)
- **Sample cols**: TPM (`float32`), STAR-counted reads normalized to gene length & total mapped reads

#### `mirna_bcgsc.reads_per_million.txt` — miRNA expression

- **Shape**: 1,881 miRNAs × (1 feature col + 11,442 sample cols)
- **Feature col**: `miRNA_ID` (mirBase v21 mature miRNA name, e.g., `hsa-let-7a-1`)
- **Sample cols**: reads per million miRNA-mapped reads (`float32`)

#### `dnam_sesame_{27k,450k,epic_v2}.beta_value.txt` — DNA methylation β-values

Three separate matrices, one per array platform.

| Matrix | Probes | Samples |
|---|---:|---:|
| 27K | 27,578 | 2,663 |
| 450K | 486,427 | 9,812 |
| EPIC v2 | 930,659 | 53 (LUAD only) |

- **Feature col**: `IlmnID` (Illumina probe ID, e.g., `cg00000029`, `ch.1.2.A` for CpH, `rs0000123` for SNP-control, `ctl_<addr>` for technical-control probes)
- **Sample cols**: β-values in [0, 1] (`float32`); NaN = probe missing on this file's array
- Joins to `dnam_{27k,450k,epic_v2}.annotation.txt` (in `annotation/`) on `IlmnID`

#### `rppa.protein_expression.txt` — RPPA protein abundance

- **Shape**: 487 antibodies × (1 feature col + 7,906 sample cols)
- **Feature col**: `peptide_target` (antibody name, e.g., `AKT_pT308`, `1433BETA`)
- **Sample cols**: normalized protein expression values (`float32`, approximately log2-ratio scale, mean ~ 0)
- Joins to `rppa.annotation.txt` on `peptide_target` to get gene mapping

### 5.3 Long-format mutation table

#### `mutation.maf.txt` — pan-cancer somatic mutations

- **Shape**: 2,570,542 mutation rows × 140 cols
- **Long format** (NOT a sample × feature matrix): each row is one somatic variant called in one tumor sample. Sample identity is in `Tumor_Sample_UUID` / `Tumor_Sample_Barcode` columns.
- All 140 columns are the GDC MAF v1.0 columns; key groups:
  - **Locus**: `Hugo_Symbol`, `Entrez_Gene_Id`, `NCBI_Build` (always `GRCh38`), `Chromosome`, `Start_Position`, `End_Position`, `Strand`
  - **Variant**: `Variant_Classification` (one of 18 standard MAF classes, e.g., `Missense_Mutation`, `Silent`, `Frame_Shift_Del`), `Variant_Type` (`SNP`/`DEL`/`INS`), `Reference_Allele`, `Tumor_Seq_Allele1`, `Tumor_Seq_Allele2` (per-row: `Allele1 ≥ Allele2` string-wise — enforced by the assembler so 7-tuple uniquely identifies a mutation)
  - **Sample identity**: `Tumor_Sample_Barcode`, `Matched_Norm_Sample_Barcode`, `Tumor_Sample_UUID`, `Matched_Norm_Sample_UUID`
  - **Population AF**: `1000G_*`, `ESP_*`, `gnomAD_*`, `MAX_AF` — for germline-filtering
  - **VEP annotation**: `HGVSc`, `HGVSp`, `HGVSp_Short`, `Transcript_ID`, `Exon_Number`, `Consequence`, `IMPACT`, `BIOTYPE`, `CANONICAL`, `SIFT`, `PolyPhen`, `DOMAINS`, etc.
  - **Read support**: `t_depth`, `t_ref_count`, `t_alt_count`, `n_depth`, `n_ref_count`, `n_alt_count`
  - **Caller provenance**: `callers` (semicolon-list, e.g., `muse;mutect2;varscan2`)
  - **Misc**: `COSMIC`, `hotspot`, `GDC_FILTER`, `RNA_Support`, `case_id`

To attach per-sample metadata (cancer_type, patient_barcode, etc.) join `mutation.maf.txt` to `mutation.metadata.txt` on `Tumor_Sample_UUID`.

### 5.4 Derived mutation matrices

#### `mutation.mutation_by_case.txt` — binary mutation × case matrix

- **Shape**: 2,222,181 unique mutations × (48 description cols + 10,549 case cols)
- **Row = unique mutation feature** identified by the 7-tuple (`Chromosome`, `Start_Position`, `End_Position`, `Strand`, `Reference_Allele`, `Tumor_Seq_Allele1`, `Tumor_Seq_Allele2`).
- **First 48 cols (mutation descriptors)** — pulled from the first occurrence of each mutation in the long table: `Hugo_Symbol`, `Entrez_Gene_Id`, `NCBI_Build`, `Chromosome`, `Start_Position`, `End_Position`, `Strand`, `Variant_Classification`, `Variant_Type`, `Reference_Allele`, `Tumor_Seq_Allele1`, `Tumor_Seq_Allele2`, `dbSNP_RS`, `Mutation_Status`, `HGVSc`, `HGVSp`, `HGVSp_Short`, `Transcript_ID`, `Exon_Number`, `all_effects`, `Allele`, `Gene`, `Feature`, `Feature_type`, `One_Consequence`, `Consequence`, `cDNA_position`, `CDS_position`, `Protein_position`, `Amino_acids`, `Codons`, `TRANSCRIPT_STRAND`, `SYMBOL`, `SYMBOL_SOURCE`, `HGNC_ID`, `BIOTYPE`, `CANONICAL`, `CCDS`, `ENSP`, `SWISSPROT`, `UNIPARC`, `UNIPROT_ISOFORM`, `RefSeq`, `MANE`, `IMPACT`, `VARIANT_CLASS`, `COSMIC`, `hotspot`.
- **Sample cols (10,549)** — column header is `<tumor_barcode>, <normal_barcode>` (matches the `case` column in `mutation.metadata.txt`). Cell value is **0 or 1**: 1 if this mutation occurs in this case, 0 otherwise.
- Matrix is **99.989% sparse** (~2.57M non-zero entries out of 23.4 billion cells).

#### `mutation.gene_by_case.txt` — gene × case mutation count matrix

- **Shape**: 19,788 unique genes × (2 gene-label cols + 10,549 case cols)
- **Row = unique gene** (unique `(Hugo_Symbol, Entrez_Gene_Id)` pair).
- **First 2 cols**: `Hugo_Symbol`, `Entrez_Gene_Id`.
- **Sample cols**: same `<tumor>, <normal>` headers as the binary matrix. Cell value is **count of high-impact mutations** of that gene in that case.
- Only **9 protein-changing Variant_Classification values** contribute to the count: `Missense_Mutation`, `Nonsense_Mutation`, `Frame_Shift_Del`, `Frame_Shift_Ins`, `Splice_Site`, `In_Frame_Del`, `In_Frame_Ins`, `Translation_Start_Site`, `Nonstop_Mutation`. Silent / intron / UTR mutations are NOT counted.

---

## 6. Annotation files (in `data/_assembled/annotation/`)

### 6.1 Methylation probe annotations

Three files, one per array platform. All share `IlmnID` as the first column → joins to the methylation matrices' `IlmnID` column.

#### `dnam_450k.annotation.txt` (33 cols)

Generated from `humanmethylation450_15017482_v1-2.csv`. Columns are the Illumina HM450 manifest layout. Key cols for analysis:

| Column | Meaning |
|---|---|
| `IlmnID` / `Name` | probe ID (e.g., `cg00000029`); `ctl_<addr>` for ~850 control probes |
| `CHR` / `MAPINFO` | GRCh37 chromosome + position |
| `Genome_Build` | always `37` for HM450 |
| `Strand` / `Color_Channel` / `Next_Base` | probe-design details |
| `UCSC_RefGene_Name` | gene symbol; multi-gene probes exploded into multiple rows |
| `UCSC_RefGene_Accession` | matched RefSeq accession |
| `UCSC_RefGene_Group` | `TSS200` / `TSS1500` / `5'UTR` / `1stExon` / `Body` / `3'UTR` — promoter ⇔ `TSS200 + TSS1500 + 5'UTR` |
| `UCSC_CpG_Islands_Name` / `Relation_to_UCSC_CpG_Island` | CpG island context (`Island` / `N_Shore` / `S_Shore` / etc.) |
| `Enhancer` / `Phantom` / `DMR` / `HMM_Island` / `Regulatory_Feature_Group` / `DHS` | various regulatory annotations |

Multi-gene probes are exploded: one row per (probe, gene) pair. 807,704 rows for 486,427 unique probes.

#### `dnam_27k.annotation.txt` (34 cols)

Generated from the binary BPM file. Schema differs from 450K. Notable cols:

- `Gene_ID` (Entrez; `GeneID:` prefix stripped, just the integer)
- `Symbol`, `Synonym`, `Accession`
- `Distance_to_TSS` (signed integer)
- **`TSS_group`** — derived column inserted after `Distance_to_TSS`:
  - `<=200` → `TSS200`
  - `>200 and <=1500` → `TSS1500`
  - otherwise → empty
- `CPG_ISLAND`, `CPG_ISLAND_LOCATIONS`
- Controls section appended (with `ctl_` prefix on the IlmnID); no multi-gene explosion (HM27 is single-gene by design).

27,578 rows — one per probe.

#### `dnam_epic_v2.annotation.txt` (51 cols)

Generated from `EPIC-8v2-0_A2.csv`. Schema closer to HM450 but with extra columns (GencodeV41, Phantom5 enhancers, ENCODE CisReg sites, OpenChromatin, etc.).

**Important**: column 1 (`IlmnID`) is the **bare CG ID** (e.g., `cg25324105`) to match the data matrix. Column 2 (`Name`) holds the original replicate-suffixed Illumina ID (e.g., `cg25324105_BC11`). This swap is done so a single join key works across all three platforms.

Multi-gene exploded. 1,894,457 rows for 930,659 unique probes.

### 6.2 RPPA antibody annotation

#### `rppa.annotation.txt` (13 cols, 545 rows)

| Column | Meaning |
|---|---|
| `peptide_target` | antibody name; joins to `rppa.protein_expression.txt`'s `peptide_target` column |
| `AGID`, `lab_id`, `catalog_number` | identifiers carried over from the TCGA RPPA files |
| `gene_symbol`, `entrez_gene_id`, `uniprot_id` | gene mapping (multi-gene antibodies exploded — e.g., pan-AKT has 3 rows for AKT1/AKT2/AKT3) |
| `rrid` | antibody Research Resource ID |
| `validation_status` | MDA's QC tag (`Valid`, `Caution`, etc.) |
| `vendor`, `species`, `protein_name_official` | vendor, host species, official antibody name |
| `annotation_source` | which source matched: `MDA_T0_labid`, `MDA_T1_name`, `TCPA_catalog`, etc.; or `UNMATCHED` if no source had this antibody (22 of 487 antibodies are unmatched, with empty gene columns) |

Source files in the same directory:
- `mda_rppa_resources.html` — MDA RPPA Core Resources page (parsed with rowspan-aware HTML parser)
- `tcpa_annotation-antibody.json` — TCPA antibody panel JSON

### 6.3 Methylation array manifests (raw source files, for reference)

- `humanmethylation450_15017482_v1-2.csv` — Illumina HM450 manifest (188 MB CSV)
- `humanmethylation27_270596_v1-2.bpm` — Illumina HM27 manifest (21 MB BPM with embedded CSV)
- `EPIC-8v2-0_A2.csv` — Illumina EPIC v2 manifest (931 MB CSV)

You don't normally use these directly — `build_dnam_annotation.py` consumes them.

---

## 7. Cohort coverage

The downloaded data covers all 33 TCGA projects (~11,500 samples / ~10,000 patients total). Per-data-type sample counts:

| Data type | Pan-cancer samples | Notes |
|---|---:|---|
| Gene expression (STAR) | 11,505 | every project |
| miRNA expression (BCGSC) | 11,442 | every project |
| Methylation 450K | 9,812 | every project |
| Methylation 27K | 2,663 | early-era samples; 12 projects |
| Methylation EPIC v2 | 53 | TCGA-LUAD only |
| Copy number (ASCAT3) | 10,632 | every project |
| RPPA protein | 7,906 | 32 projects (TCGA-DLBC has none) |
| Mutations | 10,640 files / 9,558 with ≥1 mutation | 33 projects; ~2.57M total mutations |

---

## 8. Quick recipes

**Load a matrix + attach per-sample metadata (Python):**

```python
import pandas as pd

# Use parquet for speed (10-100× faster than the TSV)
ge   = pd.read_parquet("have/data/tcga/data/_assembled/ge_star.tpm_unstranded.parquet")
meta = pd.read_csv     ("have/data/tcga/data/_assembled/ge_star.metadata.txt", sep="\t")

# Long-format view: sample × gene
long = ge.set_index(["gene_id","gene_name","gene_type"]).T.reset_index()
long = long.rename(columns={"index":"file_uuid"}).merge(meta, on="file_uuid", how="left")
# Now `long` has cancer_type, sample_type, patient_barcode, etc. per sample
```

**Filter mutations to a single cancer type:**

```python
meta = pd.read_parquet("have/data/tcga/data/_assembled/mutation.metadata.txt"
                       if False else "have/data/tcga/data/_assembled/mutation.metadata.txt")
# (metadata.txt is small TSV; no parquet variant)
meta = pd.read_csv("have/data/tcga/data/_assembled/mutation.metadata.txt", sep="\t")
brca_uuids = set(meta[meta["cancer_type"]=="BRCA"]["Tumor_Sample_UUID"])
muts = pd.read_parquet("have/data/tcga/data/_assembled/mutation.maf.parquet")
brca_muts = muts[muts["Tumor_Sample_UUID"].isin(brca_uuids)]
```

**Read only a few sample columns from the 21 GB methylation parquet (very fast):**

```python
import pyarrow.parquet as pq

pf = pq.ParquetFile("have/data/tcga/data/_assembled/dnam_sesame_450k.beta_value.parquet")
my_samples = ["9188d543-e731-471f-8374-1b81051bb93d", "03393255-6cbe-40e9-9a62-838e14662755"]
df = pq.read_table(pf.source, columns=["IlmnID"] + my_samples).to_pandas()
```

**Join methylation matrix to probe annotation:**

```python
import pandas as pd

mat = pd.read_parquet("have/data/tcga/data/_assembled/dnam_sesame_450k.beta_value.parquet",
                      columns=["IlmnID"] + ["<some_sample_uuid>"])
ann = pd.read_csv("have/data/tcga/data/_assembled/annotation/dnam_450k.annotation.txt",
                  sep="\t", usecols=["IlmnID","UCSC_RefGene_Name","UCSC_RefGene_Group","CHR","MAPINFO"])
joined = mat.merge(ann, on="IlmnID", how="left")
```

---

## 9. Known gotchas

- **TCGAbiolinks GDCquery can time out** on huge cohorts (TCGA-BRCA's SNV query has ~21,000 files and times out). For affected cases, fall back to the `gdc-client` route shown in §4.1 / §4.2.
- **Per-project sample counts vary** by modality (some patients lack a particular assay). Always join the matrix to its `metadata.txt` and filter rather than assuming N samples per project.
- **Mutation `Tumor_Seq_Allele1 ≥ Tumor_Seq_Allele2` is an invariant** enforced by `assemble_mutation_maf.py`. Don't break it (e.g., by re-extracting from raw MAFs without re-applying the swap) — downstream code may rely on the 7-tuple key being canonical.
- **RPPA panel evolves over time**: 81 of 7,906 samples were assayed with an older ~247-antibody panel (~5%); their columns have NaN in the ~240 antibodies that only exist in the newer 487-panel. Filter by non-NA count or `set_id` if you need a uniform-panel cohort.
- **Methylation column header is uniformly `IlmnID`** across all three platform matrices AND all three annotation files — designed so a single join key works everywhere.
- **`download_all_tcga.sh` and `tcga_extractor_agent.py` are idempotent**: re-running them is safe — `GDCdownload` skips files already on disk and `modalities_cache.json` short-circuits the discovery phase. If you need to force re-discovery (e.g., after a transient GDCquery failure), delete the project's `modalities_cache.json` before re-running.
