from __future__ import annotations

from pathlib import Path
from typing import Any

from .deps import ConvertorDeps

# Allow-list of online-retrieval functions exposed to the DataAgent.
# Keyed by Biomni tool module → set of allowed function names within it.
ALLOWED_BIOMNI_QUERIES: dict[str, set[str]] = {
    "database": {
        "query_geo",
        "query_uniprot",
        "query_ensembl",
        "query_opentarget",
        "query_alphafold",
        "query_cbioportal",
        "query_clinvar",
        "query_pdb",
        "query_kegg",
        "query_dbsnp",
        "query_chembl",
        "query_pubchem",
        "query_gwas_catalog",
        "query_gnomad",
        "query_clinicaltrials",
        "query_dailymed",
        "query_encode",
        "query_interpro",
        "query_stringdb",
        "query_reactome",
    },
    "literature": {
        "query_pubmed",
        "query_arxiv",
        "query_scholar",
        "search_google",
    },
}


def data_lake_one_liners(deps: ConvertorDeps) -> list[dict[str, str]]:
    """Return [{key, one_line}, ...] — first sentence of each data-lake entry."""
    out = []
    for key, desc in deps.data_lake_dict.items():
        first_sentence = desc.split(".")[0].strip()
        out.append({"key": key, "one_line": first_sentence + "."})
    return out


def inspect_file(path: Path, head_rows: int = 5) -> str:
    """Open a data file and return shape + columns + a small preview.

    Dispatches by file extension. Returns plain text suitable for an LLM to read.
    Truncates output to keep it bounded.
    """
    if not path.exists():
        return f"ERROR: file does not exist: {path}"

    suffix = path.suffix.lower()

    try:
        if suffix == ".parquet":
            import pandas as pd
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(path)
            cols = list(pf.schema_arrow.names)
            n_rows = pf.metadata.num_rows
            n_cols = len(cols)
            preview_cols = cols[: min(10, n_cols)]
            df_head = pd.read_parquet(path, columns=preview_cols).head(head_rows)
            return (
                f"Parquet: {n_rows} rows x {n_cols} cols.\n"
                f"First 10 col names: {preview_cols}\n\n"
                f"Head (first 10 cols, {head_rows} rows):\n{df_head.to_string(max_cols=10)}"
            )

        if suffix in {".csv", ".tsv", ".txt"}:
            import pandas as pd

            sep = "\t" if suffix in {".tsv", ".txt"} else ","
            try:
                df = pd.read_csv(path, sep=sep, nrows=head_rows)
                return (
                    f"{suffix} table: {df.shape[1]} cols.\n"
                    f"Columns: {list(df.columns)}\n\n"
                    f"Head ({head_rows} rows):\n{df.to_string(max_cols=20)}"
                )
            except Exception:
                text = path.read_text(errors="replace")[:2000]
                return f"Could not parse {path.name} as a table. First 2KB as text:\n{text}"

        if suffix == ".h5ad":
            import anndata as ad

            a = ad.read_h5ad(path, backed="r")
            return (
                f"AnnData: {a.shape[0]} obs x {a.shape[1]} vars\n"
                f"obs cols (first 20): {list(a.obs.columns)[:20]}\n"
                f"var cols (first 20): {list(a.var.columns)[:20]}"
            )

        if suffix == ".json":
            text = path.read_text(errors="replace")[:2000]
            return f"JSON (first 2KB):\n{text}"

        if suffix == ".pkl":
            import pickle

            with path.open("rb") as f:
                obj = pickle.load(f)
            return (
                f"Pickle: top-level type = {type(obj).__name__}\n"
                f"Repr (first 1KB): {repr(obj)[:1000]}"
            )

        if suffix in {".md", ".rst"}:
            text = path.read_text(errors="replace")[:4000]
            return f"{suffix} (first 4KB):\n{text}"

        # Unknown extension: report size and a small text head.
        size = path.stat().st_size
        try:
            preview = path.read_text(errors="replace")[:1000]
        except Exception:
            preview = "(binary)"
        return f"Unknown extension {suffix}. Size: {size} bytes.\nPreview:\n{preview}"

    except Exception as e:
        return f"ERROR inspecting {path.name}: {type(e).__name__}: {e}"


def call_biomni_query(module: str, function_name: str, kwargs: dict[str, Any]) -> str:
    """Call an allow-listed Biomni query function and return its result as text."""
    allowed = ALLOWED_BIOMNI_QUERIES.get(module)
    if allowed is None:
        return (
            f"ERROR: module '{module}' is not exposed. "
            f"Allowed modules: {sorted(ALLOWED_BIOMNI_QUERIES)}"
        )
    if function_name not in allowed:
        return (
            f"ERROR: function '{function_name}' is not allow-listed in module "
            f"'{module}'. Allowed: {sorted(allowed)}"
        )

    try:
        import importlib

        mod = importlib.import_module(f"biomni.tool.{module}")
        func = getattr(mod, function_name)
    except Exception as e:
        return f"ERROR importing biomni.tool.{module}.{function_name}: {type(e).__name__}: {e}"

    try:
        result = func(**kwargs)
        text = str(result)
        if len(text) > 10_000:
            text = text[:10_000] + "\n...[truncated to 10K chars]"
        return text
    except Exception as e:
        return f"ERROR calling {module}.{function_name}({kwargs!r}): {type(e).__name__}: {e}"


def list_module_tools(deps: ConvertorDeps, module: str) -> list[dict[str, str]]:
    """Return [{name, description}, ...] for tools in a given Biomni module path."""
    schemas = deps.module2api.get(module, [])
    return [
        {"name": s.get("name", ""), "description": s.get("description", "")}
        for s in schemas
    ]


def get_tool_schema(deps: ConvertorDeps, module: str, name: str) -> dict | None:
    """Return the full schema dict for a tool, or None if not found."""
    for s in deps.module2api.get(module, []):
        if s.get("name") == name:
            return s
    return None


def search_libraries(
    deps: ConvertorDeps, query: str, category: str = "any"
) -> list[dict[str, str]]:
    """Substring/keyword filter over library_content_dict.

    category: "python" / "R" / "CLI" / "any"
    """
    q = query.lower()
    cat_tag = {
        "python": "[Python Package]",
        "r": "[R Package]",
        "cli": "[CLI Tool]",
    }.get(category.lower(), None)

    out = []
    for name, desc in deps.library_content_dict.items():
        if cat_tag is not None and not desc.startswith(cat_tag):
            continue
        if q in name.lower() or q in desc.lower():
            out.append({"name": name, "description": desc})
    return out
