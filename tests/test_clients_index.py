"""Tests for the MCP clients index and JSON schema validity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_client_capabilities import mcp_clients

_JSON_PATH = Path(__file__).parent.parent / "src" / "mcp_client_capabilities" / "mcp-clients.json"

_REQUIRED_RECORD_KEYS = {"title", "url", "protocolVersion"}

_KNOWN_CAPABILITY_KEYS = {
    "tools",
    "resources",
    "prompts",
    "roots",
    "sampling",
    "elicitation",
    "completions",
    "logging",
    "experimental",
    "tasks",
}

_CLIENT_NAMES = sorted(mcp_clients.keys())


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------


class TestClientsIndexLoading:
    """Verify the index loads correctly from JSON."""

    def test_is_non_empty_dict(self) -> None:
        assert isinstance(mcp_clients, dict)
        assert len(mcp_clients) > 0

    def test_json_file_exists(self) -> None:
        assert _JSON_PATH.exists()

    def test_json_round_trips(self) -> None:
        raw = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
        assert raw == mcp_clients


# ---------------------------------------------------------------------------
# Per-client schema validation (parametrized)
# ---------------------------------------------------------------------------


class TestClientsJsonSchema:
    """Validate every entry in mcp-clients.json has the expected shape."""

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_has_required_keys(self, name: str) -> None:
        record = mcp_clients[name]
        missing = _REQUIRED_RECORD_KEYS - set(record.keys())
        assert not missing, f"missing: {missing}"

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_protocol_version_is_string(self, name: str) -> None:
        assert isinstance(mcp_clients[name]["protocolVersion"], str)

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_title_is_non_empty_string(self, name: str) -> None:
        title = mcp_clients[name]["title"]
        assert isinstance(title, str) and title

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_url_is_string(self, name: str) -> None:
        assert isinstance(mcp_clients[name]["url"], str)

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_only_known_keys(self, name: str) -> None:
        allowed = _REQUIRED_RECORD_KEYS | _KNOWN_CAPABILITY_KEYS
        unknown = set(mcp_clients[name].keys()) - allowed
        assert not unknown, f"unknown keys: {unknown}"

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_capability_values_are_dicts(self, name: str) -> None:
        record = mcp_clients[name]
        for cap_key in _KNOWN_CAPABILITY_KEYS:
            val = record.get(cap_key)
            if val is not None:
                assert isinstance(val, dict), f"{cap_key} should be dict, got {type(val)}"

    @pytest.mark.parametrize("name", _CLIENT_NAMES)
    def test_list_changed_is_bool_when_present(self, name: str) -> None:
        record = mcp_clients[name]
        for cap_key in ("tools", "resources", "prompts", "roots"):
            val = record.get(cap_key)
            if isinstance(val, dict) and "listChanged" in val:
                assert isinstance(val["listChanged"], bool), f"{cap_key}.listChanged should be bool"
