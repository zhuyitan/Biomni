import os

from biomni.config import default_config
from biomni.agent import A1

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# Database queries (indexes, retrieval, etc.) use Argo gpt54 via default_config
default_config.llm = "gpt54"
default_config.source = "Custom"
default_config.base_url = ARGO_BASE_URL
default_config.api_key = ARGO_USER

# Agent reasoning uses Biomni-R0 served via SGLang (OpenAI-compatible API on localhost:30000)
# Launch the SGLang server first:
#   conda run -n biomni_e1 python -m sglang.launch_server \
#     --model-path RyanLi0802/Biomni-R0-Preview --port 30000 --host 0.0.0.0 \
#     --mem-fraction-static 0.8 --tp 2 --trust-remote-code \
#     --json-model-override-args '{"rope_scaling":{"rope_type":"yarn","factor":1.0,"original_max_position_embeddings":32768}, "max_position_embeddings": 131072}'
agent = A1(
    path="./data",
    llm="biomni/Biomni-R0-32B-Preview",
    source="Custom",
    base_url="http://localhost:30000/v1",
    api_key="EMPTY",
)

# SGLang/Argo endpoints reject the 'stop' parameter; clear it after LLM construction
agent.llm.stop = None

agent.go("Plan a CRISPR screen to identify genes that regulate T cell exhaustion, generate 32 genes that maximize the perturbation effect.")
