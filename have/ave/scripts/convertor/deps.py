from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# have/ave/scripts/convertor/deps.py  →  parents[4] is the Biomni repo root
#   parents[0]=convertor, [1]=scripts, [2]=ave, [3]=have, [4]=<repo root>
BIOMNI_ROOT = Path(__file__).resolve().parents[4]

# Make `biomni.*` importable for the agent process.
if str(BIOMNI_ROOT) not in sys.path:
    sys.path.insert(0, str(BIOMNI_ROOT))


@dataclass
class ConvertorDeps:
    project_root: Path
    data_lake_dir: Path
    workspace_dir: Path
    data_lake_dict: dict[str, str]
    library_content_dict: dict[str, str]
    module2api: dict[str, list[dict]]


def load_deps() -> ConvertorDeps:
    from biomni.config import default_config
    from biomni.env_desc import data_lake_dict, library_content_dict
    from biomni.utils import read_module2api

    from .argo_model import ARGO_BASE_URL, ARGO_USER

    # Route Biomni's internal LLM calls through Argo. Without this, helpers
    # like query_geo / query_uniprot / query_kegg etc. (which internally call
    # biomni.tool.database._query_llm_for_api -> get_llm) default to Anthropic
    # Claude and fail with an auth error because no ANTHROPIC_API_KEY is set.
    default_config.source = "Custom"
    default_config.base_url = ARGO_BASE_URL
    default_config.api_key = ARGO_USER
    default_config.llm = "gpt54"
    default_config.temperature = 0.0

    data_lake_dir = BIOMNI_ROOT / "data" / "biomni_data" / "data_lake"
    workspace_dir = BIOMNI_ROOT / "have" / "ave" / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Throttle + retry NCBI E-utilities calls to avoid HTTP 429 rate-limit
    # failures from query_geo / query_dbsnp / query_clinvar / etc.
    # Non-NCBI endpoints pass through unchanged.
    from biomni.tool import database as _biomni_db

    _NCBI_API_KEY = os.environ.get("NCBI_API_KEY")
    _NCBI_MIN_INTERVAL = 0.11 if _NCBI_API_KEY else 0.35  # 10/sec with key, 3/sec without
    _NCBI_LAST = [0.0]
    _NCBI_LOCK = threading.Lock()
    _NCBI_HOST = "eutils.ncbi.nlm.nih.gov"

    _orig_rest_api = _biomni_db._query_rest_api

    def _throttle_ncbi():
        with _NCBI_LOCK:
            delta = time.monotonic() - _NCBI_LAST[0]
            if delta < _NCBI_MIN_INTERVAL:
                time.sleep(_NCBI_MIN_INTERVAL - delta)
            _NCBI_LAST[0] = time.monotonic()

    def _patched_rest_api(endpoint, method="GET", params=None, headers=None,
                          json_data=None, description=None):
        is_ncbi = _NCBI_HOST in (endpoint or "")
        if is_ncbi and _NCBI_API_KEY and params is not None:
            params = {**params, "api_key": _NCBI_API_KEY}

        for attempt in range(5):
            if is_ncbi:
                _throttle_ncbi()
            result = _orig_rest_api(
                endpoint, method, params, headers, json_data, description
            )
            if result.get("success"):
                return result
            err_text = str(result.get("error", ""))
            if is_ncbi and "429" in err_text and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            return result
        return result

    _biomni_db._query_rest_api = _patched_rest_api

    return ConvertorDeps(
        project_root=BIOMNI_ROOT,
        data_lake_dir=data_lake_dir,
        workspace_dir=workspace_dir,
        data_lake_dict=data_lake_dict,
        library_content_dict=library_content_dict,
        module2api=read_module2api(),
    )
