# Convertor + Evaluator Agent System

A multi-agent system that validates biology hypothesis inferences end-to-end. Given a structured **test case** describing a claim (e.g., "ATM kinase phosphorylates and activates CHK2 in lung cancer patients"), the system:

1. Locates or assembles a matching dataset,
2. Generates runnable analysis code for it,
3. Executes the code, and
4. Renders a true / false / inconclusive verdict on the original claim.

It is built on **Pydantic AI** for agent orchestration and structured output, driven by **Argo's `gpt54`** model via the OpenAI-compatible endpoint, and reuses Biomni's data lake (~97 curated files), tool catalog (~210 functions), and online query helpers (GEO, UniProt, Ensembl, ChEMBL, …). No Biomni agent code is invoked.

---

## Architecture

```
                ┌──────────────────────────────────────────────┐
                │              TestCase JSON                   │
                │  effector / target / mechanism / outcome /   │
                │  test_type / investigation_context           │
                └────────────────────┬─────────────────────────┘
                                     │
                                     ▼
                ┌──────────────────────────────────────────────┐
                │           Convertor (orchestrator)           │
                │ output_type = ConvertorOutput                │
                │ tools = delegate_to_data_agent,              │
                │         delegate_to_code_agent               │
                └────────┬────────────────────────┬────────────┘
                         │                        │
                         ▼                        ▼
       ┌────────────────────────────┐  ┌────────────────────────────┐
       │         DataAgent          │  │         CodeAgent          │
       │  output_type = DataAgent-  │  │  output_type =             │
       │       Output (Found|Not-   │  │       CodeComponent        │
       │       Found)               │  │                            │
       │  tools = data-lake search, │  │  tools = browse Biomni     │
       │          inspect, GEO      │  │          tool catalog +    │
       │          download, sandbox │  │          library catalog   │
       └────────────────────────────┘  └────────────────────────────┘
                         │                        │
                         └──────────┬─────────────┘
                                    ▼
              ┌───────────────────────────────────────────────┐
              │   AnalysisCaseOk   |   AnalysisCaseFailed     │  ──► saved to
              │   (status="ok")    |   (status=               │      <input>.result.json
              │                    |    "insufficient_data")  │
              └────────────────────┬──────────────────────────┘
                                   │
                                   │ (only when status == "ok")
                                   ▼
              ┌───────────────────────────────────────────────┐
              │   safe_exec.run_python_subprocess executes    │
              │   the generated code on the prepared data     │
              └────────────────────┬──────────────────────────┘
                                   │
                                   ▼
              ┌───────────────────────────────────────────────┐
              │                 Evaluator                     │
              │   output_type = Evaluation                    │
              │   inputs: test_case + analytical_spec +       │
              │           caveats + analysis stdout           │
              └────────────────────┬──────────────────────────┘
                                   ▼
              ┌───────────────────────────────────────────────┐
              │  verdict: "true" | "false" | "inconclusive"   │
              │  confidence + justification + key_evidence    │
              └───────────────────────────────────────────────┘
```

The **Convertor** is a thin orchestrator: it interprets the test case, delegates to the **DataAgent** to assemble data, then delegates to the **CodeAgent** to write analysis code. The **Evaluator** is invoked separately by the CLI (`run_convertor.py`), after the generated code has been executed on the prepared data.

---

## The four agents

### 1. Convertor (orchestrator)

| | |
|---|---|
| Source | [scripts/convertor/convertor_agent.py](scripts/convertor/convertor_agent.py) |
| Output type | `ConvertorOutput` = `AnalysisCaseOk` \| `AnalysisCaseFailed` (discriminated union on `status`) |
| Tools | `delegate_to_data_agent`, `delegate_to_code_agent` |

The Convertor's job is to translate a test case into an `analytical_spec` (one plain-English sentence stating the statistical test, variables, and groups), then call the DataAgent and CodeAgent in sequence. If the DataAgent returns `DataNotFound`, the Convertor short-circuits and returns `AnalysisCaseFailed` without calling the CodeAgent. If a deviation from the literal test case occurred (e.g., the agent substituted a proxy measurement), it must list each deviation in the `caveats` field of `AnalysisCaseOk`.

### 2. DataAgent

| | |
|---|---|
| Source | [scripts/convertor/data_agent.py](scripts/convertor/data_agent.py) |
| Output type | `DataAgentOutput` = `DataFound` \| `DataNotFound` (discriminator on `status`) |
| Tools | `list_data_lake_keys`, `read_data_lake_description`, `inspect_data_file`, `query_biomni_database`, `download_geo_series_tool`, `run_python_for_data_prep`, `workspace_path`, `data_lake_path` |

The DataAgent locates or assembles data for the requested analysis. Its workflow:

1. **Local first.** Browse the data lake (97 files including TCGA pan-cancer omics, DepMap, GTEx, drug-target tables, gene-interaction graphs, GWAS catalog, etc.). For each promising hit, read the full description and inspect the file (columns, shape, head).
2. **Online second.** If no local match, call `query_biomni_database` for one of the allow-listed sources (GEO, UniProt, Ensembl, OpenTargets, ChEMBL, ClinVar, dbSNP, PubMed, …). For GEO specifically, the agent first calls `download_geo_series_tool(gse_id)` — a fast path that uses GEOparse to fetch a series matrix + sample metadata as ready CSV files. It falls back to writing custom GEOparse code via `run_python_for_data_prep` for unusual series shapes.
3. **Persist.** Always write the prepared output to `have/ave/workspace/prepared_<id>.<ext>` and record an absolute file path in `DataFound.file_path`.
4. **Give up cleanly.** If no usable data can be assembled from either source, return `DataNotFound` with a clear reason and lists of what was attempted.

The sandbox (`run_python_for_data_prep`) is a fresh subprocess with `cwd` set to the workspace and a 600-second default timeout.

### 3. CodeAgent

| | |
|---|---|
| Source | [scripts/convertor/code_agent.py](scripts/convertor/code_agent.py) |
| Output type | `CodeComponent` |
| Tools | `list_biomni_tool_modules`, `list_tools_in_module`, `get_tool_schema`, `search_libraries`, `read_library_description` |

The CodeAgent receives the `analytical_spec` and the `DataFound` (file path + schema summary) and produces a complete, self-contained runnable code block. It does **not** execute the code — that's done by `run_convertor.py` after the Convertor returns. The agent chooses one of three strategies:

- `biomni_tool` — wrap a Biomni domain function (e.g., from `biomni.tool.genomics`) with the prepared file path as input.
- `library_call` — write code that uses a known Python / R package from the biomni_e1 environment (scipy.stats, scanpy, DESeq2 via rpy2, etc.). The most common pick for standard statistical tests.
- `custom_code` — write the statistical analysis from scratch when no tool or library is a good fit.

The catalog-browsing tools follow a hierarchical pattern: list modules → list tools in a module → fetch the full parameter schema for the chosen tool. The agent never sees all ~210 tools at once.

### 4. Evaluator

| | |
|---|---|
| Source | [scripts/convertor/evaluator.py](scripts/convertor/evaluator.py) |
| Output type | `Evaluation` |
| Tools | (none — single-shot LLM call with structured output) |

The Evaluator is invoked by `run_convertor.py` **after** the analysis code has been executed and its stdout captured. It receives the original `TestCase`, the `analytical_spec`, the `caveats`, and the raw `stdout` from the execution. It returns a verdict on whether the test case claim is supported (`true`), refuted (`false`), or undecidable (`inconclusive`), along with a confidence level and 2–4 concrete numeric findings (`key_evidence`) drawn from the analysis output.

The Evaluator is intentionally separate from the Convertor: the Convertor decides *how* to test the claim, the Evaluator decides *what the results mean*. Keeping them apart lets the Convertor's structured output be saved and re-evaluated later without re-running the agent pipeline.

---

## Input — `TestCase` schema

Defined in [scripts/convertor/models.py](scripts/convertor/models.py).

| Field | Type | Description |
|---|---|---|
| `effector` | `str` | The entity initiating the relationship (e.g., "ATM kinase"). |
| `target` | `str` | The entity being affected (e.g., "CHK2"). |
| `mechanism_description` | `str` | How the effector influences the target (e.g., "phosphorylates and activates"). |
| `outcome` | `str` | The expected result of the interaction (e.g., "Increased levels of phosphorylated CHK2"). |
| `test_type` | `dict` | Two keys: `observation_manipulation` ("observation" \| "manipulation") and `type` ("association" \| "correlation" \| …). |
| `investigation_context` | `dict` | Population descriptors + `data_type`. Shape varies by `test_type.type`. |

`investigation_context` shape:

- **Association test** — `case_population`, `control_population`, `data_type`.
- **Correlation test** — `population`, `data_type`.

### Example 1 — association test

```json
{
  "effector": "ATM kinase",
  "target": "CHK2",
  "mechanism_description": "phosphorylates and activates",
  "outcome": "Increased levels of phosphorylated CHK2",
  "test_type": {
    "observation_manipulation": "observation",
    "type": "association"
  },
  "investigation_context": {
    "case_population": "lung cancer patients with ATM kinase overexpression",
    "control_population": "lung cancer patients without ATM kinase overexpression",
    "data_type": "gene expression"
  }
}
```

### Example 2 — correlation test

```json
{
  "effector": "APOE",
  "target": "TYROBP",
  "mechanism_description": "upregulates",
  "outcome": "increased expression level of TYROBP",
  "test_type": {
    "observation_manipulation": "observation",
    "type": "correlation"
  },
  "investigation_context": {
    "population": "patients with Alzheimer's disease",
    "data_type": "gene expression"
  }
}
```

---

## Convertor output schemas

The Convertor returns a discriminated union on the `status` field.

### Branch A — `AnalysisCaseOk` (`status == "ok"`)

| Field | Type | Description |
|---|---|---|
| `status` | `"ok"` | Discriminator. |
| `test_case` | `TestCase` | Original input echoed for traceability. |
| `analytical_spec` | `str` | Plain-English statement of the statistical test the system chose. |
| `data` | `DataFound` | The prepared data component (see below). |
| `code` | `CodeComponent` | The generated analysis code (see below). |
| `rationale` | `str` | Why this data + analysis approach was chosen. |
| `caveats` | `list[str]` | One entry per deviation from the literal test case. Format: `"<field>: requested <X> but used <Y> because <reason>"`. Empty when the analysis matches the test case verbatim. |

`DataFound`:

| Field | Type | Description |
|---|---|---|
| `status` | `"found"` | Discriminator. |
| `source` | `"data_lake"` \| `"online"` \| `"generated"` | Where the data came from. |
| `source_detail` | `str` | Specific source (e.g. `"TCGA pan-cancer gene expression (tcga_ge_star.tpm_unstranded.parquet) joined to metadata, subset to LUAD+LUSC"`). |
| `file_path` | `str` \| `null` | Absolute path to the prepared file (CSV/parquet/…). |
| `schema_summary` | `str` | Columns, dtypes, shape — enough for the CodeAgent to write code against without re-inspecting. |
| `preparation_steps` | `list[str]` | Human-readable log of what the agent did. |

`CodeComponent`:

| Field | Type | Description |
|---|---|---|
| `strategy` | `"biomni_tool"` \| `"library_call"` \| `"custom_code"` | Which approach was chosen. |
| `language` | `"python"` \| `"R"` \| `"bash"` | Language of `runnable_code`. |
| `tool_reference` | `ToolReference` \| `null` | Populated only when `strategy == "biomni_tool"`; contains `module`, `function_name`, `invocation_kwargs`. |
| `runnable_code` | `str` | Complete, self-contained executable text. References `data.file_path`. |
| `expected_inputs` | `str` | What files/objects the code reads. |
| `expected_outputs` | `str` | What the code writes/returns. |

Truncated real example:

```json
{
  "status": "ok",
  "test_case": { "effector": "ATM kinase", "target": "CHK2", "..." },
  "analytical_spec": "Two-group association test on CHEK2 expression between ATM-high and ATM-low lung cancer patients using Welch's t-test with Mann-Whitney fallback.",
  "data": {
    "status": "found",
    "source": "data_lake",
    "source_detail": "Prepared from TCGA pan-cancer gene expression matrix joined to sample metadata, restricted to lung tumor samples",
    "file_path": "/.../have/ave/workspace/prepared_tcga_lung_atm_chk2_expression.csv",
    "schema_summary": "CSV with 1,053 rows × 12 columns; one row per TCGA lung tumor sample (LUAD or LUSC). Key columns: ATM_tpm, CHEK2_tpm, ATM_overexpression_status (bool), cancer_type.",
    "preparation_steps": ["Listed local data lake...", "Read TCGA descriptions...", "..."]
  },
  "code": {
    "strategy": "library_call",
    "language": "python",
    "tool_reference": null,
    "runnable_code": "import pandas as pd\nfrom scipy import stats\n... [truncated] ...",
    "expected_inputs": "CSV at /.../prepared_tcga_lung_atm_chk2_expression.csv with CHEK2_tpm and ATM_overexpression_status columns.",
    "expected_outputs": "Printed test statistics, p-values, and effect sizes; CSV file with detailed results."
  },
  "rationale": "TCGA lung tumor gene expression directly matches the requested observational association in lung cancer patients...",
  "caveats": [
    "outcome: requested 'Increased levels of phosphorylated CHK2' but used CHEK2 gene expression because phospho-CHK2 measurements were unavailable in the matched lung cancer dataset",
    "case_population: requested 'lung cancer patients with ATM kinase overexpression' but used samples with ATM expression in the top quartile because overexpression status was not explicitly annotated and had to be operationalized from RNA-seq TPM values"
  ]
}
```

### Branch B — `AnalysisCaseFailed` (`status == "insufficient_data"`)

| Field | Type | Description |
|---|---|---|
| `status` | `"insufficient_data"` | Discriminator. |
| `test_case` | `TestCase` | Original input echoed for traceability. |
| `analytical_spec` | `str` | What the system intended to run. |
| `reason` | `str` | Why no analysis case could be produced. |
| `attempted_data_lake_keys` | `list[str]` | Data-lake files the agent inspected before giving up. |
| `attempted_online_queries` | `list[str]` | Online lookups it tried. |

Example:

```json
{
  "status": "insufficient_data",
  "test_case": { "...": "..." },
  "analytical_spec": "Association test on phospho-ATM between radiation-exposed vs unexposed lung cancer patients.",
  "reason": "TCGA RPPA contains ATM and ATM_pS1981 phospho-protein measurements in lung tumors, but no ionizing-radiation exposure variable is present in the TCGA sample metadata. Without an exposure variable, the requested association analysis cannot be run from the available data.",
  "attempted_data_lake_keys": ["tcga_rppa.protein_expression.parquet", "tcga_rppa.metadata.txt"],
  "attempted_online_queries": []
}
```

---

## Evaluator output — `Evaluation` schema

| Field | Type | Description |
|---|---|---|
| `verdict` | `"true"` \| `"false"` \| `"inconclusive"` | The verdict on the test case claim. |
| `confidence` | `"high"` \| `"medium"` \| `"low"` | How confident the evaluator is in the verdict. |
| `justification` | `str` | 2–4 sentences explaining the verdict, including caveat impact. |
| `key_evidence` | `list[str]` | 2–4 short bullets quoting the specific numbers (p-values, effect sizes, correlations) that drove the verdict. |

Example (real output for the ATM → CHK2 case):

```json
{
  "verdict": "false",
  "confidence": "high",
  "justification": "The claim is refuted: ATM-high tumors do not show increased phospho-CHK2 relative to ATM-low tumors, and all association tests are strongly null. Confidence slightly tempered by caveats that ATM 'overexpression' was operationalized as median-split ATM RNA and the outcome used RPPA phospho-protein rather than gene expression.",
  "key_evidence": [
    "Welch t-test for CHK2_pT68: mean difference (ATM_high - ATM_low) = -0.0088, p = 0.742",
    "Mann-Whitney U: median difference = 0.0015, p = 0.573",
    "Histology-adjusted OLS: ATM_high coefficient = -9.6e-05, 95% CI [-0.052, +0.051], p = 0.997",
    "Group means essentially identical: 0.170 vs 0.178 (n = 342 vs 344)"
  ]
}
```

---

## Code structure

```
have/ave/
├── README.md                       (this document)
├── scripts/
│   ├── run_convertor.py            CLI entrypoint: convertor → execute → evaluator
│   └── convertor/
│       ├── __init__.py             (empty marker)
│       ├── models.py               All Pydantic schemas (TestCase, DataFound/NotFound,
│       │                           CodeComponent, AnalysisCaseOk/Failed, Evaluation)
│       ├── argo_model.py           gpt54 wired to Argo OpenAI-compatible endpoint;
│       │                           defines ARGO_BASE_URL, ARGO_USER, ARGO_MODEL_SETTINGS
│       ├── deps.py                 Shared ConvertorDeps + load_deps(); also wires
│       │                           Biomni's default_config to Argo and installs an
│       │                           NCBI rate-limit throttle/retry patch
│       ├── catalog.py              Data-lake + tool-catalog helpers; allow-listed
│       │                           Biomni query dispatch; download_geo_series helper
│       ├── safe_exec.py            Subprocess sandbox for generated/data-prep code
│       ├── data_agent.py           DataAgent (8 tools)
│       ├── code_agent.py           CodeAgent (5 tools)
│       ├── convertor_agent.py      Orchestrator (2 delegate tools)
│       └── evaluator.py            Evaluator (no tools, structured output only)
└── workspace/                      Runtime scratch dir: prepared data files,
                                    GEO downloads, .result.json outputs, run logs
```

The Biomni assets used (read-only) live outside this tree:

- `biomni/env_desc.py` — `data_lake_dict` (97 file descriptions) + `library_content_dict` (114 package descriptions).
- `biomni/utils.py` — `read_module2api()` loads schemas for ~210 tool functions.
- `biomni/tool/*.py` — domain modules (genomics, pharmacology, …) and database query helpers.
- `data/biomni_data/data_lake/` — the 99 actual data files (parquet, csv, h5ad, …).

---

## Setup and prerequisites

1. **Conda env.** Activate `biomni_e1` (already provisioned for this project):
   ```
   conda activate biomni_e1
   ```
   Key dependencies in this env: `pydantic-ai-slim[openai]` (≥1.107.0), `GEOparse` (≥2.0.4), `pandas`, `scipy`, `pyarrow`, plus the full Biomni domain stack.

2. **Network.** The system requires outbound HTTPS to Argonne's internal Argo endpoint (`https://apps.inside.anl.gov/argoapi/v1`) and to NCBI's E-utilities + FTP hosts. You must be on-site or connected via Argonne VPN.

3. **Identity.** Argo authenticates by passing your ANL domain username as the "API key". The default identity is hardcoded as `yitan.zhu` in [scripts/convertor/argo_model.py](scripts/convertor/argo_model.py). Edit the `ARGO_USER` constant there to change identity.

4. **Optional speedup — NCBI API key.** NCBI's E-utilities throttle anonymous clients to 3 req/sec. Registering a free API key raises this to 10 req/sec. To use one:
   ```
   export NCBI_API_KEY=<your-32-char-key>
   ```
   Get one at https://www.ncbi.nlm.nih.gov/account/ → Settings → API Key Management. The system picks it up automatically on next run.

---

## Tutorial — running the system end-to-end

### Step 1 — write a test case JSON

Save the following as `have/ave/workspace/my_test_case.json`:

```json
{
  "effector": "ATM kinase",
  "target": "CHK2",
  "mechanism_description": "phosphorylates and activates",
  "outcome": "Increased levels of phosphorylated CHK2",
  "test_type": {
    "observation_manipulation": "observation",
    "type": "association"
  },
  "investigation_context": {
    "case_population": "lung cancer patients with ATM kinase overexpression",
    "control_population": "lung cancer patients without ATM kinase overexpression",
    "data_type": "gene expression"
  }
}
```

### Step 2 — invoke the CLI

```
python have/ave/scripts/run_convertor.py have/ave/workspace/my_test_case.json
```

Expected wall-clock: ~6–10 minutes per case (convertor delegation ~6 min, code execution ~30 s – 2 min, evaluator ~30 s). GEO retrieval cases take a few minutes longer.

### Step 3 — read the printed sections

The CLI prints (in order):

1. **CONVERTOR OUTPUT (full)** — the entire `AnalysisCaseOk` or `AnalysisCaseFailed` as JSON.
2. **PREPARED DATA FILE** — the absolute path of the prepared data on disk. *(Only on `status="ok"`.)*
3. **GENERATED ANALYSIS CODE** — the full `runnable_code` string from the `CodeComponent`. *(Only on `status="ok"`.)*
4. **ANALYSIS RESULTS** — stdout + stderr of executing the code in a subprocess. *(Only on `status="ok"`.)*
5. **EVALUATION** — the Evaluator's `verdict`, `confidence`, `justification`, and `key_evidence`. *(Only on `status="ok"`.)*
6. **USAGE** — token counts and request counts for the convertor and evaluator runs.

On the **insufficient_data** branch, sections 2–5 are replaced by a single `NO ANALYSIS CASE GENERATED` block with the `reason` field, then the usage stats.

### Step 4 — locate the saved result

The CLI also writes `have/ave/workspace/my_test_case.result.json` containing exactly `result.output.model_dump_json(indent=2)` — the structured convertor output (either branch). Useful for downstream processing or re-evaluation.

To re-load it programmatically:

```python
import json, sys
sys.path.insert(0, 'have/ave/scripts')
from convertor.models import AnalysisCaseOk, AnalysisCaseFailed

obj = json.load(open('have/ave/workspace/my_test_case.result.json'))
cls = AnalysisCaseOk if obj['status'] == 'ok' else AnalysisCaseFailed
output = cls.model_validate(obj)

if output.status == 'ok':
    print(output.data.file_path)
    print(output.code.runnable_code)
    for c in output.caveats:
        print('Caveat:', c)
else:
    print('Failed:', output.reason)
```

### Step 5 — interpret the verdict

The Evaluator's verdict has three values:

- **`true`** — the analysis output supports the claim (effect in the expected direction AND statistically meaningful).
- **`false`** — the analysis output refutes the claim (effect in the opposite direction, or null when a non-null effect was predicted).
- **`inconclusive`** — the analysis failed to run, the effect is borderline, the sample size is too small, or caveats indicate the measurement is too distant a proxy for the claim.

Always cross-reference the verdict with `caveats` from the convertor — if the analysis substituted a proxy (e.g., mRNA in place of phospho-protein), a `false` verdict refutes the proxy, not necessarily the original claim.

---

## Configuration knobs

| What | Where | Default |
|---|---|---|
| Argo model id | `convertor/argo_model.py` → `make_argo_model("gpt54")` | `gpt54` |
| Argo username | `convertor/argo_model.py` → `ARGO_USER` | `"yitan.zhu"` |
| Argo base URL | `convertor/argo_model.py` → `ARGO_BASE_URL` | `https://apps.inside.anl.gov/argoapi/v1` |
| Sampling temperature | `convertor/argo_model.py` → `ARGO_MODEL_SETTINGS` | `temperature=0` (deterministic) |
| Workspace directory | `convertor/deps.py` → `load_deps()` | `have/ave/workspace/` |
| Subprocess timeout for data-prep | `convertor/data_agent.py` → `run_python_for_data_prep` `timeout_s` | `600` seconds |
| Subprocess timeout for analysis execution | `run_convertor.py` → `_execute_code` | `600` seconds |
| NCBI throttle interval | `convertor/deps.py` → `_NCBI_MIN_INTERVAL` | `0.35s` anonymous / `0.11s` with `NCBI_API_KEY` |
| NCBI API key | env var `NCBI_API_KEY` | unset (anonymous 3/sec) |
| Allow-listed online query functions | `convertor/catalog.py` → `ALLOWED_BIOMNI_QUERIES` | ~20 NCBI/REST query helpers + 4 literature search functions |

---

## Known limitations

- **Fresh subprocess per data-prep call.** Each `run_python_for_data_prep` invocation is an isolated subprocess — no Python state persists across calls. The agent cannot do incremental REPL-style debugging the way Biomni's A1 agent can.
- **Single-shot Evaluator.** The Evaluator runs once on the captured stdout; it does not re-run the analysis with adjusted parameters or call back into the system for refinement.
- **Run-to-run wording variance.** Even at `temperature=0`, gpt54 is only near-deterministic. Verdicts and structured fields are stable across re-runs in the common case, but free-text fields (`rationale`, `justification`) may vary slightly. Borderline cases (e.g., missing metadata that the agent might or might not catch) can occasionally route to different branches.
- **GEO retrieval covers the common case.** `download_geo_series_tool` handles bulk RNA-seq and microarray series with a `VALUE` column. Unusual layouts (single-cell HDF5, supplementary-file-only data, multi-platform splits) require the agent to fall back to writing custom GEOparse code, which is slower and more error-prone.
- **`<input>.result.json` only stores the convertor output.** The analysis execution stdout and the Evaluator verdict are printed to the console but not persisted in the saved JSON. Re-loading the result file gives you the data + code components and lets you re-execute them yourself.
- **Biomni `_query_llm_for_api` is rerouted through Argo.** This is done at `load_deps()` time. If you also need to use Biomni's own A1 agent in the same process and want it to use a different model, you will need to set `biomni.config.default_config` back to your intended values after `load_deps()`.
