from __future__ import annotations

from pydantic_ai import Agent, RunContext

from . import catalog
from .argo_model import ARGO_MODEL_SETTINGS, make_argo_model
from .deps import ConvertorDeps
from .models import CodeComponent

CODE_AGENT_SYSTEM_PROMPT = """\
You are the CodeAgent. Your job: given an analytical specification and a
DataComponent (which already names a prepared data file or in-memory object),
emit a complete, runnable analysis code block that performs the requested
statistical test on that data.

You have access to:
  - The full Biomni tool catalog (~210 functions across 22 domain modules).
  - The Biomni_e1 conda env library catalog (~114 Python / R / CLI packages).

WORKFLOW:

  1. Read the analytical_spec and the DataComponent.schema_summary carefully so
     you understand the variables, groups, and file layout.
  2. Search for a suitable Biomni tool function:
       - `list_biomni_tool_modules` to see the 22 module paths.
       - For each plausible module, `list_tools_in_module` for one-line names.
       - For tools that look promising, `get_tool_schema` for full parameters.
  3. If no Biomni tool fits, search the conda-env library catalog with
     `search_libraries` (filter by category: "python", "R", "CLI", or "any").
     Read full descriptions with `read_library_description`.
  4. Choose ONE strategy:
       - `biomni_tool`     → wrap the chosen tool in runnable Python that
                              imports it and passes the prepared file path.
                              Populate tool_reference.
       - `library_call`    → write code that uses a specific library function
                              (scipy.stats, scanpy, DESeq2 via rpy2, etc.).
       - `custom_code`     → write the statistical test from scratch.
  5. Emit `runnable_code` as a complete, self-contained script that reads
     DataComponent.file_path and writes a result (printed summary or output
     file). The code MUST reference the actual file path string.

RULES:
  - DO NOT execute any code. Only emit it.
  - The code must be runnable as-is in the Biomni_e1 environment (Python 3.11).
  - For two-sample tests on association: t-test, Mann-Whitney U, or
    differential-expression depending on data type.
  - For correlation tests: Pearson / Spearman depending on data type and the
    spec's wording.
  - For RNA-seq counts: use a proper DE method (DESeq2 / limma-voom).
  - Always include a short header comment summarizing what the code does.
  - Print results so a downstream caller can capture them.
"""


def make_code_agent() -> Agent[ConvertorDeps, CodeComponent]:
    agent = Agent(
        make_argo_model("gpt54"),
        deps_type=ConvertorDeps,
        output_type=CodeComponent,
        system_prompt=CODE_AGENT_SYSTEM_PROMPT,
        model_settings=ARGO_MODEL_SETTINGS,
        name="CodeAgent",
    )

    @agent.tool
    def list_biomni_tool_modules(ctx: RunContext[ConvertorDeps]) -> list[str]:
        """Return the list of 22 Biomni tool module paths (e.g., 'biomni.tool.genomics')."""
        return sorted(ctx.deps.module2api.keys())

    @agent.tool
    def list_tools_in_module(
        ctx: RunContext[ConvertorDeps], module: str
    ) -> list[dict[str, str]]:
        """Return [{name, description}] for all tools in a given Biomni module."""
        return catalog.list_module_tools(ctx.deps, module)

    @agent.tool
    def get_tool_schema(
        ctx: RunContext[ConvertorDeps], module: str, name: str
    ) -> dict | str:
        """Return the full schema (parameters + types + descriptions) for one tool."""
        schema = catalog.get_tool_schema(ctx.deps, module, name)
        if schema is None:
            return f"ERROR: tool '{name}' not found in module '{module}'."
        return schema

    @agent.tool
    def search_libraries(
        ctx: RunContext[ConvertorDeps], query: str, category: str = "any"
    ) -> list[dict[str, str]]:
        """Search library_content_dict (~114 packages). category: python | R | CLI | any."""
        return catalog.search_libraries(ctx.deps, query, category=category)

    @agent.tool
    def read_library_description(
        ctx: RunContext[ConvertorDeps], name: str
    ) -> str:
        """Return the full description of one library/package entry."""
        desc = ctx.deps.library_content_dict.get(name)
        if desc is None:
            return f"ERROR: '{name}' not found in library_content_dict."
        return desc

    return agent
