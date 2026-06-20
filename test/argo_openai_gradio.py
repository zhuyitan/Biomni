import os

from biomni.agent import A1
from biomni.config import default_config

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# Route tools that read default_config (literature + database helpers) through
# Argo's OpenAI-compatible endpoint. biomni.llm.get_llm sees a non-"claude-"
# prefix on names like "claudesonnet47" and a base_url, so it picks the
# "Custom" branch — a ChatOpenAI client that POSTs to {base_url}/chat/completions.
# That requires the /v1 suffix; without it the URL is /argoapi/chat/completions
# and Argo returns 404. The A1 agent still uses gpt54 from its own ctor args.
default_config.llm = "claudesonnet46"  # valid Argo Claude IDs: claudesonnet46, claudeopus47, claudehaiku45 (no claudesonnet47)
default_config.api_key = ARGO_USER
default_config.base_url = ARGO_BASE_URL

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

agent.launch_gradio_demo()

# In terminal of local computer, construct the tunnel and open the provided URL in your browser to access the Gradio interface.
# ssh -L 7860:localhost:7860 yitan.zhu@lambda0.cels.anl.gov
# Access the server using http://localhost:7860/
