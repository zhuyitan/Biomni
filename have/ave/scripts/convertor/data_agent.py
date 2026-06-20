from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext

from . import catalog
from .argo_model import ARGO_MODEL_SETTINGS, make_argo_model
from .deps import ConvertorDeps
from .models import DataAgentOutput
from .safe_exec import run_python_subprocess

DATA_AGENT_SYSTEM_PROMPT = """\
You are the DataAgent. Your job: given an analytical specification and a test case,
locate or assemble the data needed to run that analysis, and return a structured
DataComponent describing what is ready on disk (or report not_found).

You have access to:
  - A local data lake of ~97 curated files. PREFER this source.
  - An allow-listed set of Biomni online query functions (GEO, UniProt, Ensembl,
    OpenTargets, ChEMBL, ClinVar, dbSNP, PubMed, …) when local data is missing.
  - A sandboxed Python executor to subset / merge / clean / download data and
    persist the result to the shared workspace directory.

WORKFLOW (follow in order, stop as soon as you have prepared data):

  1. Call `list_data_lake_keys` to see what is available locally. Identify any
     keys whose one-line summary plausibly matches the test case's
     investigation_context.data_type, populations, and biological entities
     (effector/target).
  2. For each promising key, call `read_data_lake_description` for full schema /
     column / join-key information, then `inspect_data_file` on the candidate
     file (and any sibling metadata file mentioned in its description) to
     confirm columns and shape.
  3. Write a Python script and call `run_python_for_data_prep` to:
       - load the relevant data lake file(s),
       - subset to the rows/columns needed (e.g., specific gene, cancer type,
         tumor vs normal samples, case vs control populations),
       - write the prepared output to `<workspace>/prepared_<short_id>.<ext>`
         (parquet or csv preferred). PRINT the absolute output path so you can
         reference it.
  4. If no local match exists, call `query_biomni_database` (e.g., query_geo for
     GEO accession listings). Then use `run_python_for_data_prep` to download
     and prepare the data into the workspace.
  5. If after both local and online attempts you cannot assemble suitable data,
     return DataNotFound with a clear reason and a list of what you tried.

RULES:
  - When you finish successfully, the `file_path` MUST be an absolute path to a
    file that actually exists in the workspace, and `schema_summary` MUST
    describe its columns / shape / dtypes well enough for a downstream code
    generator to write analysis code against it without re-inspecting.
  - `preparation_steps` must be a human-readable log: what you searched, what
    you loaded, how you subset, where you saved.
  - Be decisive. Do not spend turns inspecting files that are obviously
    unrelated. Three to five tool calls is typical for the happy path.
"""


def make_data_agent() -> Agent[ConvertorDeps, DataAgentOutput]:
    agent = Agent(
        make_argo_model("gpt54"),
        deps_type=ConvertorDeps,
        output_type=DataAgentOutput,
        system_prompt=DATA_AGENT_SYSTEM_PROMPT,
        model_settings=ARGO_MODEL_SETTINGS,
        name="DataAgent",
    )

    @agent.tool
    def list_data_lake_keys(ctx: RunContext[ConvertorDeps]) -> list[dict[str, str]]:
        """Return [{key, one_line}] for every file in the local data lake.

        `one_line` is the first sentence of each entry's description. Use this
        to spot candidates; then call read_data_lake_description for full text.
        """
        return catalog.data_lake_one_liners(ctx.deps)

    @agent.tool
    def read_data_lake_description(
        ctx: RunContext[ConvertorDeps], key: str
    ) -> str:
        """Return the full description of one data-lake file (schema, join keys, units)."""
        desc = ctx.deps.data_lake_dict.get(key)
        if desc is None:
            return f"ERROR: '{key}' not found in data_lake_dict."
        return desc

    @agent.tool
    def inspect_data_file(
        ctx: RunContext[ConvertorDeps], filename: str, head_rows: int = 5
    ) -> str:
        """Open `filename` from the local data lake and return shape + columns + a preview."""
        path = ctx.deps.data_lake_dir / filename
        return catalog.inspect_file(path, head_rows=head_rows)

    @agent.tool
    def query_biomni_database(
        ctx: RunContext[ConvertorDeps],
        module: str,
        function_name: str,
        kwargs: dict[str, Any],
    ) -> str:
        """Call an allow-listed Biomni query function for online data retrieval.

        Allowed modules: "database" or "literature".
        Examples:
          query_biomni_database("database", "query_geo", {"prompt": "lung cancer ATM expression"})
          query_biomni_database("literature", "query_pubmed", {"query": "CHK2 phosphorylation", "max_papers": 5})
        """
        return catalog.call_biomni_query(module, function_name, kwargs)

    @agent.tool
    def run_python_for_data_prep(
        ctx: RunContext[ConvertorDeps], code: str, timeout_s: int = 300
    ) -> str:
        """Run a standalone Python script in a sandboxed subprocess.

        The script's working directory is the shared workspace. Print absolute
        paths of any files you write. Returns combined stdout+stderr.
        Use this to load+subset data-lake files, to download from the web, or
        to validate that prepared output is correct.
        """
        return run_python_subprocess(
            code, workspace=ctx.deps.workspace_dir, timeout_s=timeout_s
        )

    @agent.tool
    def workspace_path(ctx: RunContext[ConvertorDeps]) -> str:
        """Return the absolute path of the workspace dir. Use it when constructing output paths."""
        return str(ctx.deps.workspace_dir)

    @agent.tool
    def data_lake_path(ctx: RunContext[ConvertorDeps]) -> str:
        """Return the absolute path of the local data-lake dir. Use it to construct file loads."""
        return str(ctx.deps.data_lake_dir)

    return agent
