import os

from biomni.agent import A1
from biomni.config import default_config

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# Choose which Argo model handles database/index/retrieval calls.
# Recommended values in Argo: "gpt54" or "claudeopus47"
ARGO_DB_MODEL = os.environ.get("ARGO_DB_MODEL", "gpt54")

# Biomni-R0 reasoning endpoint (served locally via SGLang, OpenAI-compatible API)
# Example: python -m sglang.launch_server --model-path RyanLi0802/Biomni-R0-Preview --port 30000 ...
BIOMNI_R0_BASE_URL = os.environ.get("BIOMNI_R0_BASE_URL", "http://localhost:30000/v1")
BIOMNI_R0_MODEL = os.environ.get("BIOMNI_R0_MODEL", "biomni/Biomni-R0-32B-Preview")

# 1) Configure global/default LLM for database queries and related operations.
default_config.path = "./data"
default_config.llm = ARGO_DB_MODEL
default_config.source = "Custom"
default_config.base_url = ARGO_BASE_URL
default_config.api_key = ARGO_USER

# 2) Configure A1 reasoning model to Biomni-R0 endpoint.
agent = A1(
    path="./data",
    llm=BIOMNI_R0_MODEL,
    source="Custom",
    base_url=BIOMNI_R0_BASE_URL,
    api_key="EMPTY",
)

agent.go(
    "Plan a CRISPR screen to identify genes that regulate T cell exhaustion, "
    "generate 32 genes that maximize the perturbation effect."
)
