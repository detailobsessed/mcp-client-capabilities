#!/usr/bin/env python3
"""Copy the local probe DB into the repo.

Usage:
    uv run python scripts/sync-probes.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_REPO_DB = _ROOT / "src" / "mcp_client_capabilities" / "mcp-clients-2026.json"
_LOCAL_DB = Path.home() / "mcp-probes" / "mcp-clients-2026.json"


def main() -> None:
    if not _LOCAL_DB.exists():
        print(f"No local DB found at {_LOCAL_DB}")
        return

    try:
        data = _LOCAL_DB.read_text(encoding="utf-8")
        json.loads(data)  # validate before copying
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Invalid local DB: {exc}")
        return

    shutil.copy2(_LOCAL_DB, _REPO_DB)
    print(f"Copied {_LOCAL_DB} → {_REPO_DB}")


if __name__ == "__main__":
    main()
