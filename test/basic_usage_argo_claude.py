import os

from biomni.agent import A1

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# NOTE: source="Anthropic" uses Argo's native Anthropic Messages endpoint, which
# routes through Google Cloud Vertex AI. Vertex AI does not support assistant
# message prefill, which Biomni's agentic loop requires. source="Custom" uses
# Argo's OpenAI-compatible endpoint instead, which handles the Claude translation
# internally and does not have this restriction.

# claudeopus47 = Claude Opus 4.7 (newest/most capable Claude in Argo production)
# Argo silently drops temperature/top_p/top_k for this model on the OpenAI-
# compatible endpoint, so no patching is needed for sampling parameters.
agent = A1(
    path="./data",
    llm="claudeopus47",
    source="Custom",
    base_url=ARGO_BASE_URL,
    api_key=ARGO_USER,
)

# Argo rejects the 'stop' parameter for Claude models; clear it after construction
agent.llm.stop = None

agent.go("Predict ADMET properties for this compound: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O")

agent.go("Plan a CRISPR screen to identify genes that regulate T cell exhaustion, generate 32 genes that maximize the perturbation effect.")
