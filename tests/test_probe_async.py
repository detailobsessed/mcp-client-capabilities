"""Tests for async middleware hooks and deep probe functions.

These tests mock the MCP context/middleware objects to exercise the
async code paths without a real MCP connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from mcp_client_capabilities.probe_server import (
    _CapabilityCaptureMW,
    _probe_elicitation,
    _probe_roots,
    _probe_sampling,
    _run_deep_probe,
)

# ---------------------------------------------------------------------------
# Middleware hook tests
# ---------------------------------------------------------------------------


class TestOnInitialize:
    """Test the on_initialize middleware hook."""

    @pytest.mark.anyio
    async def test_captures_client_info(self, mw: _CapabilityCaptureMW, tmp_output: Path) -> None:
        params = MagicMock()
        params.clientInfo.model_dump.return_value = {"name": "TestClient", "version": "2.0"}
        params.protocolVersion = "2025-03-26"
        params.capabilities.model_dump.return_value = {"roots": {"listChanged": True}}

        context = MagicMock()
        context.message.params = params

        call_next = AsyncMock(return_value=None)
        await mw.on_initialize(context, call_next)

        assert mw._client_info == {"name": "TestClient", "version": "2.0"}
        assert mw._protocol_version == "2025-03-26"
        assert mw._declared == {"roots": {"listChanged": True}}
        call_next.assert_awaited_once_with(context)
        assert tmp_output.exists()  # noqa: ASYNC240

    @pytest.mark.anyio
    async def test_captures_multiple_declared_capabilities(self, mw: _CapabilityCaptureMW) -> None:
        params = MagicMock()
        params.clientInfo.model_dump.return_value = {"name": "Full"}
        params.protocolVersion = "2025-06-18"
        params.capabilities.model_dump.return_value = {
            "roots": {},
            "sampling": {},
            "elicitation": {},
            "experimental": {"custom": True},
        }
        context = MagicMock()
        context.message.params = params

        await mw.on_initialize(context, AsyncMock())

        assert "roots" in mw._declared
        assert "sampling" in mw._declared
        assert "elicitation" in mw._declared
        assert mw._declared["experimental"] == {"custom": True}

    @pytest.mark.anyio
    async def test_ignores_non_declared_capabilities(self, mw: _CapabilityCaptureMW) -> None:
        params = MagicMock()
        params.clientInfo.model_dump.return_value = {"name": "Minimal"}
        params.protocolVersion = "2025-03-26"
        params.capabilities.model_dump.return_value = {"tools": {"listChanged": True}}
        context = MagicMock()
        context.message.params = params

        await mw.on_initialize(context, AsyncMock())

        assert mw._declared == {}


class TestOnListHooks:
    """Test the on_list_* middleware hooks."""

    @pytest.mark.anyio
    async def test_on_list_tools(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        call_next = AsyncMock(return_value="result")

        result = await mw.on_list_tools(context, call_next)

        assert result == "result"
        assert mw._list_counts["tools"] == 1
        assert "tools" in mw._observed
        assert "tools/list" in mw._observed["tools"]

    @pytest.mark.anyio
    async def test_on_list_resources(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        result = await mw.on_list_resources(context, AsyncMock(return_value="res"))

        assert result == "res"
        assert mw._list_counts["resources"] == 1
        assert "resources/list" in mw._observed["resources"]

    @pytest.mark.anyio
    async def test_on_list_resource_templates(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        result = await mw.on_list_resource_templates(context, AsyncMock(return_value="tpl"))

        assert result == "tpl"
        assert mw._list_counts["resources"] == 1
        assert "resources/templates/list" in mw._observed["resources"]

    @pytest.mark.anyio
    async def test_on_list_prompts(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        result = await mw.on_list_prompts(context, AsyncMock(return_value="prompts"))

        assert result == "prompts"
        assert mw._list_counts["prompts"] == 1
        assert "prompts/list" in mw._observed["prompts"]

    @pytest.mark.anyio
    async def test_on_read_resource(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        result = await mw.on_read_resource(context, AsyncMock(return_value="data"))

        assert result == "data"
        assert "resources/read" in mw._observed["resources"]

    @pytest.mark.anyio
    async def test_on_get_prompt(self, mw: _CapabilityCaptureMW) -> None:
        context = MagicMock()
        result = await mw.on_get_prompt(context, AsyncMock(return_value="prompt"))

        assert result == "prompt"
        assert "prompts/get" in mw._observed["prompts"]

    @pytest.mark.anyio
    async def test_list_counts_accumulate(self, mw: _CapabilityCaptureMW) -> None:
        for _ in range(3):
            await mw.on_list_tools(MagicMock(), AsyncMock())
        assert mw._list_counts["tools"] == 3


# ---------------------------------------------------------------------------
# Tier 3: active probe functions
# ---------------------------------------------------------------------------


class TestProbeRoots:
    """Test _probe_roots with mocked context."""

    @pytest.mark.anyio
    async def test_success(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        ctx.list_roots.return_value = [MagicMock(), MagicMock()]

        await _probe_roots(ctx, mw)

        assert mw._active["roots"] is True
        assert "2 root(s)" in mw._active_evidence["roots"]

    @pytest.mark.anyio
    async def test_failure(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        ctx.list_roots.side_effect = Exception("not supported")

        await _probe_roots(ctx, mw)

        assert mw._active["roots"] is False
        assert "Exception" in mw._active_evidence["roots"]


class TestProbeSampling:
    """Test _probe_sampling with mocked context."""

    @pytest.mark.anyio
    async def test_success(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        result = MagicMock()
        result.text = "probe-ok"
        ctx.sample.return_value = result

        await _probe_sampling(ctx, mw)

        assert mw._active["sampling"] is True
        assert "probe-ok" in mw._active_evidence["sampling"]

    @pytest.mark.anyio
    async def test_success_with_none_text(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        result = MagicMock()
        result.text = None
        ctx.sample.return_value = result

        await _probe_sampling(ctx, mw)

        assert mw._active["sampling"] is True

    @pytest.mark.anyio
    async def test_failure(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        ctx.sample.side_effect = ValueError("unsupported")

        await _probe_sampling(ctx, mw)

        assert mw._active["sampling"] is False
        assert "ValueError" in mw._active_evidence["sampling"]


class TestProbeElicitation:
    """Test _probe_elicitation with mocked context."""

    @pytest.mark.anyio
    async def test_success(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        result = MagicMock()
        result.action = "accept"
        ctx.elicit.return_value = result

        await _probe_elicitation(ctx, mw)

        assert mw._active["elicitation"] is True
        assert "accept" in mw._active_evidence["elicitation"]

    @pytest.mark.anyio
    async def test_failure(self, mw: _CapabilityCaptureMW) -> None:
        ctx = AsyncMock()
        ctx.elicit.side_effect = RuntimeError("no elicitation")

        await _probe_elicitation(ctx, mw)

        assert mw._active["elicitation"] is False
        assert "RuntimeError" in mw._active_evidence["elicitation"]


# ---------------------------------------------------------------------------
# _run_deep_probe — full integration with mocked context
# ---------------------------------------------------------------------------


class TestRunDeepProbe:
    """Test _run_deep_probe end-to-end with mocked context."""

    @pytest.mark.anyio
    async def test_full_probe_returns_result(self, mw: _CapabilityCaptureMW, tmp_output: Path) -> None:
        # Pre-populate observed so listChanged logic runs
        mw._observed["tools"] = ["tools/list"]
        mw._list_counts["tools"] = 1

        ctx = AsyncMock()
        ctx.send_notification = AsyncMock()
        ctx.list_roots.return_value = [MagicMock()]
        sampling_result = MagicMock()
        sampling_result.text = "ok"
        ctx.sample.return_value = sampling_result
        elicit_result = MagicMock()
        elicit_result.action = "accept"
        ctx.elicit.return_value = elicit_result

        with patch("mcp_client_capabilities.probe_server._NOTIFICATION_WAIT_SECONDS", 0):
            result = await _run_deep_probe(ctx, mw)

        assert "capabilities" in result
        assert "clientRecord" in result
        assert result["capabilities"]["roots"]["supported"] is True
        assert result["capabilities"]["sampling"]["supported"] is True
        assert result["capabilities"]["elicitation"]["supported"] is True
        # listChanged should be set for tools (not re-listed → False)
        assert mw._list_changed["tools"] is False
        assert tmp_output.exists()  # noqa: ASYNC240

    @pytest.mark.anyio
    async def test_probe_with_all_failures(self, mw: _CapabilityCaptureMW, tmp_output: Path) -> None:
        ctx = AsyncMock()
        ctx.send_notification = AsyncMock()
        ctx.list_roots.side_effect = Exception("fail")
        ctx.sample.side_effect = Exception("fail")
        ctx.elicit.side_effect = Exception("fail")

        with patch("mcp_client_capabilities.probe_server._NOTIFICATION_WAIT_SECONDS", 0):
            result = await _run_deep_probe(ctx, mw)

        assert result["capabilities"]["roots"]["supported"] is False
        assert result["capabilities"]["sampling"]["supported"] is False
        assert result["capabilities"]["elicitation"]["supported"] is False

    @pytest.mark.anyio
    async def test_notification_send_failure_suppressed(self, mw: _CapabilityCaptureMW, tmp_output: Path) -> None:
        ctx = AsyncMock()
        ctx.send_notification.side_effect = Exception("notification failed")
        ctx.list_roots.side_effect = Exception("fail")
        ctx.sample.side_effect = Exception("fail")
        ctx.elicit.side_effect = Exception("fail")

        with patch("mcp_client_capabilities.probe_server._NOTIFICATION_WAIT_SECONDS", 0):
            result = await _run_deep_probe(ctx, mw)

        assert "capabilities" in result
