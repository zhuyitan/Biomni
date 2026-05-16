import os

from biomni.agent import A1

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# Argo model name for GPT-4o is "gpt4o" (see Argo API docs for full model list)
# agent = A1(
#     path="./data",
#     llm="gpt4o",
#     source="Custom",
#     base_url=ARGO_BASE_URL,
#     api_key=ARGO_USER,
# )

# Argo model name for GPT-5.4 is "gpt54" (production; 1M token context, 128K output)
agent = A1(
    path="./data",
    llm="gpt54",
    source="Custom",
    base_url=ARGO_BASE_URL,
    api_key=ARGO_USER,
)

# Argo's gpt4o rejects the 'stop' parameter; clear it after LLM construction
agent.llm.stop = None

# agent.go("Plan a CRISPR screen to identify genes that regulate T cell exhaustion, generate 32 genes that maximize the perturbation effect.")

agent.go("Predict ADMET properties for this compound: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O")
