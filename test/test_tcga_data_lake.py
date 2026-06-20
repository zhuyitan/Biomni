"""Smoke test: ask A1 a TCGA question to verify the new data lake entries land in
the system prompt and the agent answers from the symlinked TCGA files (not by
downloading from GDC).

Expected trajectory: agent reads tcga_data_description.md, then loads
tcga_ge_star.metadata.txt, groups by `cancer_type`, returns a count table per
cancer type.

Run from anywhere; the data path is resolved relative to the repo root so
biomni_data/data_lake/ resolves to the lake we populated."""

import json
import os

from biomni.agent import A1

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(REPO_ROOT, "data")

ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

agent = A1(
    path=DATA_PATH,
    llm="gpt54",
    source="Custom",
    base_url=ARGO_BASE_URL,
    api_key=ARGO_USER,
)
agent.llm.stop = None  # Argo rejects the 'stop' parameter

flag_pub_val = False
flag_exact_condition = False

HYPOTHESES_JSON = os.path.join(
    REPO_ROOT, "test", "data_test_cases", "yitan_three_hypotheses.json"
)

# List of 3 hypothesis dicts. Each item has keys:
#   id (str), text (str), candidate_inferences (list of dicts with
#   effector / target / mechanism_description / outcome / investigation_context)
with open(HYPOTHESES_JSON) as f:
    HYPOTHESES = json.load(f)
print(f"Loaded {len(HYPOTHESES)} hypotheses from {HYPOTHESES_JSON}")
for h in HYPOTHESES:
    print(f"  - id={h['id']}, candidate_inferences={len(h['candidate_inferences'])}")

for h in HYPOTHESES:
    print(f"Hypothesis {h['id']} text: {h['text']}")
    for i, inf in enumerate(h["candidate_inferences"]):
        print(f"Hypothesis {h['id']} inference {i}:")
        for k in ["effector", "target", "mechanism_description", "outcome", "investigation_context"]:
            print(f"  {k}: {inf[k]}")
        
        prompt = "You need to validate a single-step hypothesis inference. The inference is in a structured dictionary format." \
            "In this dictionary, the keys represent different components of the inference, including 'effector', 'target', 'mechanism_description', 'outcome', and 'investigation_context'. " \
            "Effector is the entity starting a relationship/mechanism, and target is the entity being affected. " \
            "Mechanism_description describes how the effector influences the target, and outcome describes the result of this interaction. " \
            "Investigation_context is a dictionary, and it has a dictionary element named 'population'. " \
            "Population has two keys: 'organism' and 'stage_or_condition', which provide additional information about the conditions under which this inference is made. " \

        if flag_pub_val:
            prompt += "To validate this hypothesis inference, you can first check if there is evidence in the scientific " \
                "literature that supports the relationship/mechanism described between the effector and target, " \
                "as well as the outcome, in the specified population. If the hypothesis inference is supported by literature evidence, " \
                "generate a dictionary with the following keys: 'evidence_type', 'evidence_strength', 'additional_info'. " \
                "evidence_type is a string 'literature', indicating that the supporting evidence comes from scientific literature. " \
                "evidence_strength is a string that can be 'strong', 'moderate', or 'weak', indicating the strength of the evidence supporting the validation. " \
                "additional_info is a string including the PubMed IDs of papers and their conclusions supporting the inference. " \
                "If there is no evidence in the literature to support the inference, you need to perform data analysis to validate it. " \
                "Data analysis should use data related to the specified population to check if the relationship/mechanism described between the effector and target, " \
                "as well as the outcome, holds. If the hypothesis inference is supported by data analysis results, " \
                "generate a dictionary with the following keys: 'evidence_type', 'evidence_strength', 'additional_info'. " \
                "evidence_type is a string 'data_analysis', indicating that the supporting evidence comes from data analysis. " \
                "evidence_strength is a numeric value of the major statistic metric used to evaluate the evidence strength. " \
                "additional_info is a string including details of the data analysis supporting the inference. "
        else:
            prompt += "You need to perform data analysis to validate the hypothesis inference. " \
                "Data analysis should use data related to the specified population to check if the relationship/mechanism described between the effector and target, " \
                "as well as the outcome, holds. The more closely the data matches the specified population, the more reliable the validation will be. " \
                "If the hypothesis inference is supported by data analysis results, " \
                "generate a dictionary with the following keys: 'evidence_type', 'evidence_strength', 'additional_info'. " \
                "evidence_type is a string 'data_analysis', indicating that the supporting evidence comes from data analysis. " \
                "evidence_strength is a numeric value of the major statistic metric used to evaluate the evidence strength. " \
                "additional_info is a string including details of the data analysis supporting the inference. "            
        if flag_exact_condition:
            prompt += "When validating the hypothesis inference using data analysis, you need to ensure that the data you use for validation exactly matches the 'population' specified in the 'investigation_context' of the inference. " \
                "This means that the organism and stage_or_condition of the data should be the same as those specified in the 'population' of the 'investigation_context'. " \
                "If you cannot find data that exactly matches the specified population, you should not use data with a different population for validation, as it may not provide accurate evidence for the inference. " \
                "In such cases, you should indicate that there is insufficient data to validate the inference rather than using mismatched data. " \
                "It is important to ensure that the validation of the hypothesis inference is based on relevant and appropriate data, which can provide more accurate and reliable evidence for the inference. "
        prompt += "Please provide your validation result in a JSON format. The JSON should be a dictionary with the keys 'evidence_type', 'evidence_strength', and 'additional_info' as described above. " \
            "If the hypothesis inference cannot be validated, please provide a JSON with 'evidence_type' set to null, 'evidence_strength' set to null, and 'additional_info' describing the reason for insufficient evidence. " \
            "You can print the JSON result in terminal. "
        prompt += "Here is the hypothesis inference you need to validate: " + json.dumps(inf, indent=2)
        agent.go(prompt)



# QUESTION = (
#     "In TCGA data, how many DNA methylation data samples are there per cancer type? "
# )

# QUESTION = (
#     "Please tell me the top 10 genes whose expressions are the most significantly differentially expressed between " 
#     "breast invasive carcinomas (BRCA) and normal tissues. These 10 genes need to have a fold change greater than 2. "
#     "Differential expression should be ranked by p-value. Please provide the gene names and their corresponding p-values."
# )

# QUESTION = (
#     "I need to know the average DNA methylation level in the TSS region of PTEN gene in ovarian cancer."
# )


