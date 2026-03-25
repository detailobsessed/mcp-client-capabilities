"""Shared fixtures for the mcp-client-capabilities test suite."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mcp_client_capabilities.probe_server import _CapabilityCaptureMW

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Temporary DB path for probe results."""
    return tmp_path / "mcp-clients-2026.json"


@pytest.fixture
def mw(tmp_output: Path) -> _CapabilityCaptureMW:
    """Fresh middleware instance with a temporary DB path."""
    return _CapabilityCaptureMW(tmp_output)


def read_client_entry(db_path: Path, client_name: str = "unknown") -> dict[str, Any]:
    """Read a client's entry from the DB file."""
    db = json.loads(db_path.read_text(encoding="utf-8"))
    return db[client_name]
