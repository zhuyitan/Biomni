from __future__ import annotations

import sys
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
    from biomni.env_desc import data_lake_dict, library_content_dict
    from biomni.utils import read_module2api

    data_lake_dir = BIOMNI_ROOT / "data" / "biomni_data" / "data_lake"
    workspace_dir = BIOMNI_ROOT / "have" / "ave" / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    return ConvertorDeps(
        project_root=BIOMNI_ROOT,
        data_lake_dir=data_lake_dir,
        workspace_dir=workspace_dir,
        data_lake_dict=data_lake_dict,
        library_content_dict=library_content_dict,
        module2api=read_module2api(),
    )
