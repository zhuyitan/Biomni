from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    effector: str
    target: str
    mechanism_description: str
    outcome: str
    test_type: dict[str, Any]
    investigation_context: dict[str, Any]


# DataAgent output: either a found data component or a not-found explanation.

class DataFound(BaseModel):
    status: Literal["found"] = "found"
    source: Literal["data_lake", "online", "generated"]
    source_detail: str
    file_path: str | None = None
    schema_summary: str
    preparation_steps: list[str]


class DataNotFound(BaseModel):
    status: Literal["not_found"] = "not_found"
    reason: str
    attempted_data_lake_keys: list[str] = Field(default_factory=list)
    attempted_online_queries: list[str] = Field(default_factory=list)


DataAgentOutput = Annotated[
    Union[DataFound, DataNotFound], Field(discriminator="status")
]


# CodeAgent output: always a CodeComponent (only produced when data is found).

class ToolReference(BaseModel):
    module: str
    function_name: str
    invocation_kwargs: dict[str, Any] = Field(default_factory=dict)


class CodeComponent(BaseModel):
    strategy: Literal["biomni_tool", "library_call", "custom_code"]
    language: Literal["python", "R", "bash"]
    tool_reference: ToolReference | None = None
    runnable_code: str
    expected_inputs: str
    expected_outputs: str


# Orchestrator output: either a complete AnalysisCase or an insufficient-data report.

class AnalysisCaseOk(BaseModel):
    status: Literal["ok"] = "ok"
    test_case: TestCase
    analytical_spec: str
    data: DataFound
    code: CodeComponent
    rationale: str
    caveats: list[str] = Field(default_factory=list)
    # Each entry: one concise statement of how the prepared artifact differs
    # from the literal test case. Format: "<field>: requested <X> but used <Y>
    # because <reason>". Empty list means no divergence from the test case.


class AnalysisCaseFailed(BaseModel):
    status: Literal["insufficient_data"] = "insufficient_data"
    test_case: TestCase
    analytical_spec: str
    reason: str
    attempted_data_lake_keys: list[str] = Field(default_factory=list)
    attempted_online_queries: list[str] = Field(default_factory=list)


ConvertorOutput = Annotated[
    Union[AnalysisCaseOk, AnalysisCaseFailed], Field(discriminator="status")
]


# Evaluator output: a verdict on whether the test case is supported by the
# analysis results that came out of running the convertor's generated code.

class Evaluation(BaseModel):
    verdict: Literal["true", "false", "inconclusive"]
    confidence: Literal["high", "medium", "low"]
    justification: str
    key_evidence: list[str] = Field(default_factory=list)
    # 2-4 short bullets quoting the specific numbers (p-values, effect sizes,
    # correlation coefficients, group differences) that drove the verdict.
