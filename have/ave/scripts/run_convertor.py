"""CLI entrypoint for the Convertor agent.

Usage:
    python have/ave/scripts/run_convertor.py <path-to-test-case.json>

End-to-end pipeline per invocation:
  1. Convertor produces an AnalysisCase (prepared data file + analysis code).
  2. If status == "ok", the analysis code is executed on the prepared data.
  3. The Evaluator agent reads the test case + caveats + analysis output and
     returns a true/false/inconclusive verdict.

The test case JSON must match the TestCase schema (effector, target,
mechanism_description, outcome, test_type, investigation_context).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `convertor` package importable when run as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from convertor.convertor_agent import make_convertor_agent  # noqa: E402
from convertor.deps import load_deps  # noqa: E402
from convertor.evaluator import make_evaluator_agent  # noqa: E402
from convertor.models import TestCase  # noqa: E402
from convertor.safe_exec import run_python_subprocess  # noqa: E402


def _execute_code(language: str, code: str, workspace: Path) -> str:
    """Dispatch execution by language and return combined stdout/stderr."""
    if language == "python":
        return run_python_subprocess(code, workspace=workspace, timeout_s=600)
    if language == "R":
        from biomni.utils import run_r_code  # noqa: PLC0415
        return str(run_r_code(code))
    if language == "bash":
        from biomni.utils import run_bash_script  # noqa: PLC0415
        return str(run_bash_script(code))
    return f"[ERROR] Unsupported language: {language!r}. Code was not executed."


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    test_case_path = Path(sys.argv[1])
    raw = json.loads(test_case_path.read_text())
    test_case = TestCase.model_validate(raw)

    deps = load_deps()
    convertor = make_convertor_agent()

    prompt = (
        "Convert the following test case into an AnalysisCase. "
        "Follow the procedure in your system prompt.\n\n"
        f"TEST CASE JSON:\n{test_case.model_dump_json(indent=2)}"
    )

    result = convertor.run_sync(prompt, deps=deps)
    output = result.output

    print("=" * 80)
    print("CONVERTOR OUTPUT (full)")
    print("=" * 80)
    print(output.model_dump_json(indent=2))
    print()

    # Persist convertor output (works for both ok and insufficient_data).
    result_path = test_case_path.with_suffix(".result.json")
    result_path.write_text(output.model_dump_json(indent=2))
    print(f"Saved convertor result to: {result_path}")
    print()

    if output.status != "ok":
        print("=" * 80)
        print("NO ANALYSIS CASE GENERATED")
        print("=" * 80)
        print(f"Reason: {output.reason}")
        print()
        print("=" * 80)
        print(f"USAGE: {result.usage}")
        print("=" * 80)
        return 0

    # --- Status == "ok": show prepared data + generated code -----------------
    print("=" * 80)
    print("PREPARED DATA FILE")
    print("=" * 80)
    print(output.data.file_path)
    print()

    print("=" * 80)
    print(f"GENERATED ANALYSIS CODE ({output.code.language})")
    print("=" * 80)
    print(output.code.runnable_code)
    print()

    # --- Execute the code on the prepared data ------------------------------
    print("=" * 80)
    print(f"ANALYSIS RESULTS (executing {output.code.language} code)")
    print("=" * 80)
    exec_output = _execute_code(
        output.code.language, output.code.runnable_code, deps.workspace_dir
    )
    print(exec_output)
    print()

    # --- Evaluate the results vs the test case claim ------------------------
    print("=" * 80)
    print("EVALUATION (test case true / false / inconclusive)")
    print("=" * 80)
    evaluator = make_evaluator_agent()
    eval_prompt = (
        f"TEST CASE:\n{output.test_case.model_dump_json(indent=2)}\n\n"
        f"ANALYTICAL SPEC:\n{output.analytical_spec}\n\n"
        f"CAVEATS (deviations from the literal test case):\n"
        f"{json.dumps(output.caveats, indent=2)}\n\n"
        f"ANALYSIS OUTPUT (stdout/stderr of the executed code):\n{exec_output}"
    )
    eval_result = evaluator.run_sync(eval_prompt)
    e = eval_result.output
    print(f"VERDICT:       {e.verdict.upper()}")
    print(f"CONFIDENCE:    {e.confidence}")
    print(f"JUSTIFICATION: {e.justification}")
    print("KEY EVIDENCE:")
    for ev in e.key_evidence:
        print(f"  - {ev}")
    print()

    print("=" * 80)
    print(f"CONVERTOR USAGE: {result.usage}")
    print(f"EVALUATOR USAGE: {eval_result.usage}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
