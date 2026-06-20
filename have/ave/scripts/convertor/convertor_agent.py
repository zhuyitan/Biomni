from __future__ import annotations

from pydantic_ai import Agent, RunContext

from .argo_model import ARGO_MODEL_SETTINGS, make_argo_model
from .code_agent import make_code_agent
from .data_agent import make_data_agent
from .deps import ConvertorDeps
from .models import (
    AnalysisCaseFailed,
    AnalysisCaseOk,
    CodeComponent,
    ConvertorOutput,
    DataAgentOutput,
    DataFound,
    DataNotFound,
)

CONVERTOR_SYSTEM_PROMPT = """\
You are the Convertor — the orchestrator. Given a single biology hypothesis
test case (JSON with effector, target, mechanism_description, outcome,
test_type, investigation_context), you produce an AnalysisCase: a prepared
data component + a runnable analysis code component, plus rationale.

PROCEDURE:

  1. Interpret the test case into an `analytical_spec` — one or two plain-
     English sentences naming:
       - which statistical test (association vs correlation; t-test / DESeq2 /
         Pearson / Spearman / etc.),
       - which variable(s) to compare,
       - which population(s) define the groups (case vs control for
         association; single population for correlation),
       - the relevant biological entities (effector, target) and data type.

  2. Call `delegate_to_data_agent(analytical_spec, test_case_json)`.
     The result is a discriminated union with status either "found" or
     "not_found".

  3. Branch on data status:
       - If status == "not_found": DO NOT call the code agent. Return
         AnalysisCaseFailed with the `reason`, `attempted_data_lake_keys`,
         and `attempted_online_queries` copied from the DataAgent response,
         plus the original test_case and your analytical_spec.
       - If status == "found": call `delegate_to_code_agent(analytical_spec,
         data_component_json)` where data_component_json is the JSON of the
         DataFound. Then assemble AnalysisCaseOk with the test_case,
         analytical_spec, data, code, and a short `rationale` explaining
         your choice of data and analysis approach.

DIVERGENCE REPORTING:
  Whenever the prepared data or chosen analysis deviates from the literal
  test case (different data modality than investigation_context.data_type,
  different population definition, different outcome variable, a proxy
  measurement, etc.), add ONE concise entry per deviation to the `caveats`
  list of AnalysisCaseOk. Format each entry as
  "<field>: requested <X> but used <Y> because <reason>". Leave `caveats`
  empty when the analysis matches the test case verbatim. Do NOT bury
  deviations in `rationale` or `analytical_spec` alone — they must be
  surfaced in `caveats` so downstream consumers can detect them
  programmatically.

RULES:
  - Echo the original test case verbatim in `test_case` for traceability.
  - Be concise. The orchestration itself should fit in 4-6 turns.
  - Do not invent data or code yourself — delegate to the sub-agents.
"""


def make_convertor_agent() -> Agent[ConvertorDeps, ConvertorOutput]:
    convertor = Agent(
        make_argo_model("gpt54"),
        deps_type=ConvertorDeps,
        output_type=ConvertorOutput,
        system_prompt=CONVERTOR_SYSTEM_PROMPT,
        model_settings=ARGO_MODEL_SETTINGS,
        name="Convertor",
    )

    data_agent = make_data_agent()
    code_agent = make_code_agent()

    @convertor.tool
    async def delegate_to_data_agent(
        ctx: RunContext[ConvertorDeps],
        analytical_spec: str,
        test_case_json: str,
    ) -> DataAgentOutput:
        """Run the DataAgent. Returns a DataFound or DataNotFound."""
        prompt = (
            f"ANALYTICAL SPEC:\n{analytical_spec}\n\n"
            f"TEST CASE (verbatim JSON):\n{test_case_json}"
        )
        result = await data_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
        return result.output

    @convertor.tool
    async def delegate_to_code_agent(
        ctx: RunContext[ConvertorDeps],
        analytical_spec: str,
        data_component_json: str,
    ) -> CodeComponent:
        """Run the CodeAgent against a prepared DataFound. Returns CodeComponent."""
        prompt = (
            f"ANALYTICAL SPEC:\n{analytical_spec}\n\n"
            f"DATA COMPONENT (JSON of the prepared data):\n{data_component_json}"
        )
        result = await code_agent.run(prompt, deps=ctx.deps, usage=ctx.usage)
        return result.output

    return convertor


# Re-export the helpers for callers
__all__ = [
    "make_convertor_agent",
    "AnalysisCaseOk",
    "AnalysisCaseFailed",
    "DataFound",
    "DataNotFound",
]
