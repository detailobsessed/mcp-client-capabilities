#!/usr/bin/env python3
"""Generate the probed-capabilities markdown table in README.md.

Reads ``src/mcp_client_capabilities/mcp-clients-2026.json`` and replaces the
content between ``<!-- MCP_PROBED_TABLE_START -->`` and
``<!-- MCP_PROBED_TABLE_END -->`` markers in ``README.md``.

Usage:
    uv run python scripts/generate-probed-table.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "src" / "mcp_client_capabilities" / "mcp-clients-2026.json"
_README_PATH = _ROOT / "README.md"

_COLUMNS = [
    ("Resources", "resources"),
    ("Prompts", "prompts"),
    ("Tools", "tools"),
    ("Discovery", "tools"),  # listChanged sub-field
    ("Sampling", "sampling"),
    ("Roots", "roots"),
    ("Elicitation", "elicitation"),
]


def _status_icon(caps: dict, cap_key: str, *, is_discovery: bool = False) -> str:
    """Return ✅, ❌, or ❓ for a capability."""
    detail = caps.get(cap_key)
    if detail is None:
        return "❓"

    value = detail.get("listChanged") if is_discovery else detail.get("supported")
    if value is True:
        return "✅"
    if value is False:
        return "❌"
    return "❓"


def generate_table(db: dict) -> str:
    """Build the markdown table from the DB."""
    header = "| Display name | Protocol | " + " | ".join(f"[{col}](#{anchor})" for col, anchor in _COLUMNS) + " | Last probed |"
    separator = "| --- | --- | " + " | ".join("---" for _ in _COLUMNS) + " | --- |"

    seen: set[str] = set()
    rows: list[str] = []

    for client_name in sorted(db, key=str.lower):
        entry = db[client_name]
        title = entry.get("clientRecord", {}).get("title", client_name)
        if title in seen:
            continue
        seen.add(title)

        url = entry.get("clientRecord", {}).get("url", "")
        display = f"[{title}]({url})" if url else title
        protocol = entry.get("protocolVersion", "")
        caps = entry.get("capabilities", {})
        captured = entry.get("capturedAt", "")[:10]  # date only

        cells = []
        for col_name, cap_key in _COLUMNS:
            is_discovery = col_name == "Discovery"
            cells.append(_status_icon(caps, cap_key, is_discovery=is_discovery))

        row = f"| {display} | {protocol} | " + " | ".join(cells) + f" | {captured} |"
        rows.append(row)

    return "\n".join([header, separator, *rows])


def main() -> None:
    if not _DB_PATH.exists():
        print(f"No DB file found at {_DB_PATH}")
        return

    db = json.loads(_DB_PATH.read_text(encoding="utf-8"))
    table = generate_table(db)

    readme = _README_PATH.read_text(encoding="utf-8")
    start_marker = "<!-- MCP_PROBED_TABLE_START -->"
    end_marker = "<!-- MCP_PROBED_TABLE_END -->"

    if start_marker not in readme:
        print(f"Marker {start_marker!r} not found in README.md — skipping.")
        return

    pattern = re.compile(
        rf"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
        re.DOTALL,
    )
    replacement = f"{start_marker}\n{table}\n{end_marker}"
    readme = pattern.sub(replacement, readme)

    _README_PATH.write_text(readme, encoding="utf-8")
    print(f"README probed table updated ({len(db)} client(s))")


if __name__ == "__main__":
    main()
