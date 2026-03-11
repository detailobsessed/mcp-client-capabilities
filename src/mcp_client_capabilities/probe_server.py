"""
MCP Capability Probe Server

A minimal MCP server that passively captures client capabilities from the
initialize handshake and writes them to a JSON file.

Usage:
    mcp-probe                              # writes ./mcp-probe-result.json
    mcp-probe --output /path/to/out.json
    MCP_PROBE_OUTPUT=out.json mcp-probe
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext

if TYPE_CHECKING:
    import mcp.types as mt

_DEFAULT_OUTPUT = "mcp-probe-result.json"


class _CapabilityCaptureMW(Middleware):
    """Middleware that intercepts the initialize handshake and saves client info."""

    def __init__(self, output_path: Path) -> None:
        self._output_path = output_path

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: Any,
    ) -> mt.InitializeResult | None:
        params = context.message.params

        result: dict[str, Any] = {
            "capturedAt": datetime.now(UTC).isoformat(),
            "clientInfo": params.clientInfo.model_dump(exclude_none=True, mode="json"),
            "protocolVersion": params.protocolVersion,
            "capabilities": params.capabilities.model_dump(
                exclude_none=True, mode="json"
            ),
        }

        try:
            self._output_path.write_text(
                json.dumps(result, indent=2, default=str),
                encoding="utf-8",
            )
            print(
                f"[mcp-probe] Captured capabilities from '{params.clientInfo.name}' "
                f"-> {self._output_path}",
                file=sys.stderr,
            )
        except OSError as exc:
            print(f"[mcp-probe] Failed to write output: {exc}", file=sys.stderr)

        return await call_next(context)


def _build_server(output_path: Path) -> FastMCP:
    mcp = FastMCP(
        name="mcp-capability-probe",
        instructions=(
            "This server probes and records the capabilities of the MCP client "
            "that connects to it. On every connection the initialize handshake is "
            "captured and written to a local JSON file. "
            "Call get_probe_results to retrieve the most recently captured data."
        ),
    )

    mcp.add_middleware(_CapabilityCaptureMW(output_path))

    @mcp.tool(
        description=(
            "Return the client capabilities captured during the most recent "
            "initialize handshake. Returns null if no capture has occurred yet."
        )
    )
    def get_probe_results() -> dict[str, Any] | None:
        """Return the last captured probe results from disk."""
        if not output_path.exists():
            return None
        return json.loads(output_path.read_text(encoding="utf-8"))

    # --- Phase 2 stub: active probing ---
    # Uncomment and implement to actively test capabilities beyond the handshake,
    # e.g. send notifications/tools/list_changed and observe client reactions.
    #
    # @mcp.tool(description="Actively probe capabilities not visible in the handshake.")
    # async def probe_active_capabilities(ctx: Context) -> dict[str, Any]:
    #     results: dict[str, Any] = {}
    #     # TODO: send ToolListChangedNotification and observe whether client
    #     #       re-lists tools
    #     # TODO: attempt sampling/elicitation requests if declared in capabilities
    #     return results

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-probe",
        description=(
            "MCP capability probe server — connects via stdio and captures "
            "client capabilities on the initialize handshake."
        ),
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("MCP_PROBE_OUTPUT", _DEFAULT_OUTPUT),
        metavar="FILE",
        help=(
            f"Path to write probe results (default: {_DEFAULT_OUTPUT!r}, "
            "env: MCP_PROBE_OUTPUT)"
        ),
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    server = _build_server(output_path)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
