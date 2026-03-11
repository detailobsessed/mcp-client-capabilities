#!/usr/bin/env python3
"""Copy the local probe DB into the repo and regenerate the README table.

Usage:
    uv run python scripts/sync-probes.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_REPO_DB = _ROOT / "src" / "mcp_client_capabilities" / "mcp-clients-2026.json"
_LOCAL_DB = Path.home() / "mcp-probes" / "mcp-clients-2026.json"


def main() -> None:
    if not _LOCAL_DB.exists():
        print(f"No local DB found at {_LOCAL_DB}")
        return

    shutil.copy2(_LOCAL_DB, _REPO_DB)
    print(f"Copied {_LOCAL_DB} → {_REPO_DB}")

    # Regenerate the README table
    subprocess.run([sys.executable, str(_ROOT / "scripts" / "generate-probed-table.py")], check=True)


if __name__ == "__main__":
    main()
