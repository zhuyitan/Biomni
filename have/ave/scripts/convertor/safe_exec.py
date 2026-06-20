from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path


def run_python_subprocess(code: str, workspace: Path, timeout_s: int = 300) -> str:
    """Run `code` as a standalone Python script in a subprocess.

    The script is written to `workspace/_prep_<uuid>.py`, executed with cwd=workspace,
    and removed afterwards. Combined stdout+stderr is returned (truncated to 10K chars).
    """
    workspace.mkdir(parents=True, exist_ok=True)
    script_path = workspace / f"_prep_{uuid.uuid4().hex[:8]}.py"
    script_path.write_text(code)

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        combined = (
            f"[exit_code={proc.returncode}]\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
    except subprocess.TimeoutExpired as e:
        combined = (
            f"[TIMEOUT after {timeout_s}s]\n"
            f"--- partial stdout ---\n{e.stdout or ''}\n"
            f"--- partial stderr ---\n{e.stderr or ''}"
        )
    except Exception as e:
        combined = f"[ERROR launching subprocess]: {type(e).__name__}: {e}"
    finally:
        try:
            script_path.unlink()
        except Exception:
            pass

    if len(combined) > 10_000:
        combined = combined[:10_000] + "\n...[truncated to 10K chars]"
    return combined
