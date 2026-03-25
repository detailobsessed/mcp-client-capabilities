"""Full-stack integration tests using FastMCP's in-memory Client.

These tests boot the actual probe server and exercise the tool/resource/prompt
handlers end-to-end without any network or subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

fastmcp = pytest.importorskip("fastmcp")
from fastmcp import Client  # noqa: E402

from mcp_client_capabilities.probe_server import _build_server  # noqa: E402


@pytest.fixture
def server(tmp_path: Path) -> fastmcp.FastMCP:
    """Build a probe server with a temp DB path."""
    return _build_server(tmp_path / "probe-db.json")


@pytest.fixture
def client(server: fastmcp.FastMCP) -> Client:
    """Create an in-memory client connected to the server."""
    return Client(server)


class TestInMemoryIntegration:
    """Exercise the full server stack via in-memory transport."""

    @pytest.mark.anyio
    async def test_list_tools(self, client: Client) -> None:
        async with client:
            tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "get_probe_results" in names
        assert "run_full_probe" in names

    @pytest.mark.anyio
    async def test_list_resources(self, client: Client) -> None:
        async with client:
            resources = await client.list_resources()
        uris = {str(r.uri) for r in resources}
        assert "probe://status" in uris

    @pytest.mark.anyio
    async def test_list_prompts(self, client: Client) -> None:
        async with client:
            prompts = await client.list_prompts()
        names = {p.name for p in prompts}
        assert "probe_summary" in names

    @pytest.mark.anyio
    async def test_get_probe_results_before_probe(self, client: Client) -> None:
        async with client:
            result = await client.call_tool("get_probe_results", {})
        # Before any probe, result should indicate no data
        assert result is not None

    @pytest.mark.anyio
    async def test_read_probe_status_resource(self, client: Client) -> None:
        async with client:
            result = await client.read_resource("probe://status")
        assert result is not None

    @pytest.mark.anyio
    async def test_get_probe_summary_prompt(self, client: Client) -> None:
        async with client:
            result = await client.get_prompt("probe_summary")
        assert result is not None
        assert len(result.messages) > 0
