from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = "yitan.zhu"

# temperature=0 reduces run-to-run variance for the convertor pipeline.
# OpenAI temp=0 is near-deterministic but not strictly so; identical inputs
# can still occasionally diverge. gpt54 accepts temperature (per Argo docs).
ARGO_MODEL_SETTINGS = ModelSettings(temperature=0)


def make_argo_model(model_id: str = "gpt54") -> OpenAIChatModel:
    return OpenAIChatModel(
        model_id,
        provider=OpenAIProvider(base_url=ARGO_BASE_URL, api_key=ARGO_USER),
    )
