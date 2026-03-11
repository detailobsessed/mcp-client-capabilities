"""
MCP Client Capabilities Index

Simple index of all MCP client capabilities loaded from JSON file.
"""

import json
from pathlib import Path

from .mcp_types import ClientsIndex, McpClientRecord

# Load client capabilities from JSON
_json_path = Path(__file__).parent / "mcp-clients.json"
with _json_path.open(encoding="utf-8") as f:
    _clients_data = json.load(f)

# All MCP client capabilities indexed by client name
mcp_clients: ClientsIndex = _clients_data  # type: ignore[assignment]

__all__ = ["ClientsIndex", "McpClientRecord", "mcp_clients"]
