import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_FILE = PROJECT_ROOT / "test" / "data_test_cases" / "yitan_three_hypotheses_v2.json"


def main():
    with DATA_FILE.open() as f:
        hypotheses = json.load(f)

    for hyp in hypotheses:
        if hyp['id'] != '01':
            continue  # For now, just print the first hypothesis and its test cases. We can expand to others later.

        print("=" * 80)
        print(f"Hypothesis id: {hyp['id']}")
        print(f"Hypothesis text: {hyp['text']}")

        for ci in hyp["candidate_inferences"]:
            print("-" * 80)
            print(f"  Candidate inference id: {ci['cand_inference_id']}")
            print(f"  Inference statement: {ci['inference_statement']}")

            for i, test_case in enumerate(ci["test_list"], start=1):
                if i != 1:
                    continue  # For now, just print the first test case for this inference. We can expand to others later.
                print(f"    Test case {i}:")
                print(json.dumps(test_case, indent=6))


if __name__ == "__main__":
    main()
