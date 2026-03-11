"""
MCP Capability Probe Server

Discovers client capabilities through three complementary strategies:

1. **Passive capture** — inspects the ``initialize`` handshake for declared
   client capabilities (roots, sampling, elicitation).
2. **Active observation** — registers a tool, resource, and prompt so the
   server advertises all three capability types, then records which MCP
   methods the client actually calls (tools/list, resources/list, etc.).
3. **Deep probing** — the ``run_full_probe`` tool sends list-changed
   notifications (to test ``listChanged`` sub-fields) and issues
   server→client requests for roots, sampling, and elicitation to
   confirm support beyond what the handshake declares.

The result is upserted into a JSON database file keyed by client name,
with fields mapping to the ``McpClientRecord`` schema in ``mcp-clients.json``.
Each probe also compares its findings against the existing database and any
previous probe for the same client.

Usage:
    mcp-probe                              # writes ~/mcp-probes/mcp-clients-2026.json
    mcp-probe --db /path/to/db.json
    MCP_PROBE_DB=db.json mcp-probe
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.server.context import Context  # noqa: TC002 — runtime use by fastmcp
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.logging import LoggingMiddleware

_DEFAULT_DB = str(Path.home() / "mcp-probes" / "mcp-clients-2026.json")
_KNOWN_CLIENTS_PATH = Path(__file__).parent / "mcp-clients.json"
_NOTIFICATION_WAIT_SECONDS = 5.0
_ACTIVE_PROBE_TIMEOUT = 15.0


def _log(msg: str) -> None:
    print(f"[mcp-probe] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Middleware — passive + active capability capture
# ---------------------------------------------------------------------------


class _CapabilityCaptureMW(Middleware):
    """Intercepts the MCP lifecycle to build a client capability profile."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._client_info: dict[str, Any] = {}
        self._protocol_version: str = ""
        self._declared: dict[str, Any] = {}
        self._observed: dict[str, list[str]] = {}
        self._list_counts: dict[str, int] = {
            "tools": 0,
            "resources": 0,
            "prompts": 0,
        }
        self._list_changed: dict[str, bool] = {}
        self._list_changed_evidence: dict[str, str] = {}
        self._active: dict[str, bool] = {}
        self._active_evidence: dict[str, str] = {}
        # Previous probe snapshot (loaded once before first write)
        self._previous_probe: dict[str, Any] | None = None
        self._previous_loaded: bool = False

    # ── helpers ────────────────────────────────────────────────────────

    _LISTABLE = ("tools", "resources", "prompts")
    _ALL_CAPS = (
        "tools",
        "resources",
        "prompts",
        "roots",
        "sampling",
        "elicitation",
        "completions",
        "logging",
    )

    def _build_capability_detail(self, key: str) -> dict[str, Any]:
        """Build detailed capability info with three-state status + evidence.

        ``supported``:
        - ``True``  — confirmed on the wire
        - ``False`` — actively tested and not supported
        - ``None``  — not yet tested (``run_full_probe`` not called)
        """
        evidence_parts: list[str] = []
        supported: bool | None = None

        if key in self._declared:
            supported = True
            evidence_parts.append("declared in initialize handshake")

        if key in self._observed:
            supported = True
            methods = ", ".join(self._observed[key])
            evidence_parts.append(f"client called {methods}")

        if key in self._active:
            if self._active[key]:
                supported = True
                evidence_parts.append(
                    self._active_evidence.get(
                        key,
                        "confirmed via server→client request",
                    ),
                )
            else:
                supported = False
                evidence_parts.append(
                    self._active_evidence.get(key, "server→client request failed"),
                )

        if supported is None and key in self._LISTABLE:
            supported = False
            evidence_parts.append(
                f"server advertised {key}, client never interacted",
            )

        detail: dict[str, Any] = {
            "supported": supported,
            "evidence": "; ".join(evidence_parts) if evidence_parts else "not tested",
        }

        if key in self._list_changed:
            detail["listChanged"] = self._list_changed[key]
            if key in self._list_changed_evidence:
                detail["evidence"] += f"; {self._list_changed_evidence[key]}"
        elif key in self._LISTABLE and supported:
            detail["listChanged"] = None

        return detail

    def _build_client_record(self) -> dict[str, Any]:
        """Build an entry matching the ``mcp-clients.json`` schema.

        Only includes capabilities confirmed as supported.
        ``listChanged`` is only included when ``True``.
        """
        record: dict[str, Any] = {
            "protocolVersion": self._protocol_version,
            "title": self._client_info.get("name", "Unknown"),
            "url": "",
        }
        for key in self._ALL_CAPS:
            detail = self._build_capability_detail(key)
            if detail["supported"] is not True:
                continue
            val: dict[str, Any] = {}
            if detail.get("listChanged") is True:
                val["listChanged"] = True
            record[key] = val

        if "experimental" in self._declared:
            record["experimental"] = self._declared["experimental"]

        return record

    def _build_result(self) -> dict[str, Any]:
        """Build the full probe output with capabilities + clientRecord."""
        capabilities = {key: self._build_capability_detail(key) for key in self._ALL_CAPS}
        if "experimental" in self._declared:
            capabilities["experimental"] = {
                "supported": True,
                "evidence": "declared in initialize handshake",
            }

        return {
            "capturedAt": datetime.now(UTC).isoformat(),
            "clientInfo": self._client_info,
            "protocolVersion": self._protocol_version,
            "capabilities": capabilities,
            "clientRecord": self._build_client_record(),
        }

    _COMPARABLE_CAPS = ("tools", "resources", "prompts", "roots", "sampling", "elicitation")

    def _compare_vs_database(self, client_key: str, client_record: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compare probe results against the existing ``mcp-clients.json``."""
        try:
            known_clients = json.loads(
                _KNOWN_CLIENTS_PATH.read_text(encoding="utf-8"),
            )
        except (OSError, json.JSONDecodeError):
            return {"status": "error", "message": "Could not read mcp-clients.json"}

        known = known_clients.get(client_key)
        if not known:
            return {
                "status": "new_client",
                "message": f"{client_key} not found in mcp-clients.json",
            }

        discrepancies: list[dict[str, str]] = []
        if client_record is None:
            client_record = self._build_client_record()
        for cap in self._COMPARABLE_CAPS:
            in_db = cap in known
            in_probe = cap in client_record
            if in_db != in_probe:
                discrepancies.append(
                    {
                        "capability": cap,
                        "database": "supported" if in_db else "absent",
                        "probe": "supported" if in_probe else "absent",
                    }
                )

        if known.get("protocolVersion") and self._protocol_version and known["protocolVersion"] != self._protocol_version:
            discrepancies.append(
                {
                    "capability": "protocolVersion",
                    "database": known["protocolVersion"],
                    "probe": self._protocol_version,
                }
            )

        if discrepancies:
            return {"status": "has_discrepancies", "discrepancies": discrepancies}
        return {"status": "match"}

    def _compare_vs_previous(self, client_record: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compare current probe against the previous probe in the DB."""
        if not self._previous_probe:
            return {"status": "first_probe", "message": "No previous probe for this client"}

        changes: list[dict[str, str]] = []
        prev_record = self._previous_probe.get("clientRecord", {})
        curr_record = client_record if client_record is not None else self._build_client_record()
        for cap in self._COMPARABLE_CAPS:
            in_prev = cap in prev_record
            in_curr = cap in curr_record
            if in_prev != in_curr:
                changes.append(
                    {
                        "capability": cap,
                        "previous": "supported" if in_prev else "absent",
                        "current": "supported" if in_curr else "absent",
                    }
                )

        if changes:
            return {"status": "has_changes", "changes": changes}
        return {"status": "no_changes"}

    def _flush(self) -> None:
        """Upsert current probe result into the DB file."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

            db: dict[str, Any] = {}
            if self._db_path.exists():
                try:
                    db = json.loads(self._db_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    _log("Corrupted DB file, starting fresh")
                    db = {}

            client_key = self._client_info.get("name", "unknown")

            # Snapshot previous probe once (before first write)
            if not self._previous_loaded:
                self._previous_loaded = True
                self._previous_probe = db.get(client_key)

            result = self._build_result()

            # Merge: never regress non-null → null (untested)
            if self._previous_probe and "capabilities" in self._previous_probe:
                prev_caps = self._previous_probe["capabilities"]
                for cap, detail in result.get("capabilities", {}).items():
                    if detail.get("supported") is None and cap in prev_caps and prev_caps[cap].get("supported") is not None:
                        result["capabilities"][cap] = prev_caps[cap]

            # Rebuild clientRecord from (possibly merged) capabilities
            merged_record: dict[str, Any] = {
                "protocolVersion": result.get("protocolVersion", ""),
                "title": result.get("clientInfo", {}).get("name", "Unknown"),
                "url": result.get("clientRecord", {}).get("url", ""),
            }
            for cap_key in self._ALL_CAPS:
                cap_detail = result["capabilities"].get(cap_key, {})
                if cap_detail.get("supported") is not True:
                    continue
                val: dict[str, Any] = {}
                if cap_detail.get("listChanged") is True:
                    val["listChanged"] = True
                merged_record[cap_key] = val
            if "experimental" in self._declared:
                merged_record["experimental"] = self._declared["experimental"]
            result["clientRecord"] = merged_record

            result["comparisonVsDatabase"] = self._compare_vs_database(client_key, merged_record)
            result["comparisonVsPreviousProbe"] = self._compare_vs_previous(merged_record)

            # Clean up "unknown" entry once we know the real name
            if client_key != "unknown" and "unknown" in db:
                del db["unknown"]

            db[client_key] = result

            self._db_path.write_text(
                json.dumps(db, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            _log(f"Failed to write DB: {exc}")

    def _observe(self, capability: str, method: str, label: str) -> None:
        """Record a newly-observed capability and flush."""
        first = capability not in self._observed
        if first:
            self._observed[capability] = []
        if method not in self._observed[capability]:
            self._observed[capability].append(method)
        if first:
            self._flush()
            _log(f"Observed: {label}")

    # ── middleware hooks ───────────────────────────────────────────────

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: Any,
    ) -> mt.InitializeResult | None:
        params = context.message.params
        self._client_info = params.clientInfo.model_dump(
            exclude_none=True,
            mode="json",
        )
        self._protocol_version = str(params.protocolVersion)

        caps = params.capabilities.model_dump(exclude_none=True, mode="json")
        self._declared = {k: caps[k] for k in ("roots", "sampling", "elicitation", "experimental") if k in caps}

        self._flush()
        name = self._client_info.get("name", "unknown")
        _log(f"Connected: {name} (protocol {self._protocol_version})")
        return await call_next(context)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: Any,
    ) -> Any:
        self._list_counts["tools"] += 1
        self._observe("tools", "tools/list", "client listed tools")
        return await call_next(context)

    async def on_list_resources(
        self,
        context: MiddlewareContext[mt.ListResourcesRequest],
        call_next: Any,
    ) -> Any:
        self._list_counts["resources"] += 1
        self._observe("resources", "resources/list", "client listed resources")
        return await call_next(context)

    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: Any,
    ) -> Any:
        self._list_counts["resources"] += 1
        self._observe(
            "resources",
            "resources/templates/list",
            "client listed resource templates",
        )
        return await call_next(context)

    async def on_list_prompts(
        self,
        context: MiddlewareContext[mt.ListPromptsRequest],
        call_next: Any,
    ) -> Any:
        self._list_counts["prompts"] += 1
        self._observe("prompts", "prompts/list", "client listed prompts")
        return await call_next(context)

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: Any,
    ) -> Any:
        self._observe("resources", "resources/read", "client read a resource")
        return await call_next(context)

    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: Any,
    ) -> Any:
        self._observe("prompts", "prompts/get", "client got a prompt")
        return await call_next(context)


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


async def _run_deep_probe(
    ctx: Context,
    mw: _CapabilityCaptureMW,
) -> dict[str, Any]:
    """Execute Tier 2 + 3 probing and return the full result."""
    # ── Tier 2: listChanged notifications ──────────────────────────

    before = dict(mw._list_counts)

    notifications = [
        (mt.ToolListChangedNotification, "tools"),
        (mt.ResourceListChangedNotification, "resources"),
        (mt.PromptListChangedNotification, "prompts"),
    ]
    for cls, _key in notifications:
        with contextlib.suppress(Exception):
            await ctx.send_notification(cls())

    await asyncio.sleep(_NOTIFICATION_WAIT_SECONDS)

    for key in ("tools", "resources", "prompts"):
        if key in mw._observed:
            changed = mw._list_counts[key] > before[key]
            mw._list_changed[key] = changed
            verb = "re-listed" if changed else "did not re-list"
            mw._list_changed_evidence[key] = f"listChanged: sent notification, client {verb} within {_NOTIFICATION_WAIT_SECONDS:.0f}s"
            _log(f"listChanged({key}): {changed}")

    # ── Tier 3: server→client requests ─────────────────────────────

    await _probe_roots(ctx, mw)
    await _probe_sampling(ctx, mw)
    await _probe_elicitation(ctx, mw)

    mw._flush()
    return mw._build_result()


async def _probe_roots(ctx: Context, mw: _CapabilityCaptureMW) -> None:
    try:
        roots = await asyncio.wait_for(
            ctx.list_roots(),
            timeout=_ACTIVE_PROBE_TIMEOUT,
        )
        mw._active["roots"] = True
        mw._active_evidence["roots"] = f"list_roots returned {len(roots)} root(s)"
        _log(f"roots: supported ({len(roots)} root(s))")
    except Exception as exc:
        mw._active["roots"] = False
        mw._active_evidence["roots"] = f"list_roots request failed: {type(exc).__name__}"
        _log(f"roots: not supported ({type(exc).__name__})")


async def _probe_sampling(ctx: Context, mw: _CapabilityCaptureMW) -> None:
    try:
        result = await asyncio.wait_for(
            ctx.sample(
                "Reply with exactly: probe-ok",
                max_tokens=10,
            ),
            timeout=_ACTIVE_PROBE_TIMEOUT,
        )
        mw._active["sampling"] = True
        mw._active_evidence["sampling"] = f"sampling request returned: {(result.text or '')[:30]!r}"
        _log(f"sampling: supported (got {(result.text or '')[:30]!r})")
    except Exception as exc:
        mw._active["sampling"] = False
        mw._active_evidence["sampling"] = f"sampling request failed: {type(exc).__name__}"
        _log(f"sampling: not supported ({type(exc).__name__})")


async def _probe_elicitation(
    ctx: Context,
    mw: _CapabilityCaptureMW,
) -> None:
    try:
        result = await asyncio.wait_for(
            ctx.elicit(
                "MCP capability probe: confirm elicitation support. Click Accept or Decline — either confirms support.",
                response_type=None,
            ),
            timeout=_ACTIVE_PROBE_TIMEOUT,
        )
        mw._active["elicitation"] = True
        mw._active_evidence["elicitation"] = f"elicitation request returned: action={result.action}"
        _log(f"elicitation: supported (action: {result.action})")
    except Exception as exc:
        mw._active["elicitation"] = False
        mw._active_evidence["elicitation"] = f"elicitation request failed: {type(exc).__name__}"
        _log(f"elicitation: not supported ({type(exc).__name__})")


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def _read_client_entry(db_path: Path, mw: _CapabilityCaptureMW) -> dict[str, Any] | None:
    """Read the current client's entry from the DB file."""
    if not db_path.exists():
        return None
    try:
        db = json.loads(db_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    client_key = mw._client_info.get("name", "unknown")
    return db.get(client_key)


def _build_server(db_path: Path) -> FastMCP:
    server = FastMCP(
        name="mcp-capability-probe",
        instructions=(
            "This server probes MCP client capabilities. "
            "First, read the probe://status resource to confirm resource support, "
            "then call the run_full_probe tool to execute a comprehensive capability scan. "
            "Results are written to a local JSON file and returned by the tool."
        ),
    )

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    mw = _CapabilityCaptureMW(db_path)
    server.add_middleware(mw)
    server.add_middleware(LoggingMiddleware(log_level=logging.DEBUG))

    # ── Tool: get_probe_results ────────────────────────────────────────

    @server.tool(
        description=("Return the client capabilities captured during this session. Returns null if no capture has occurred yet."),
    )
    def get_probe_results() -> dict[str, Any] | None:
        """Return the current client's probe results from the DB."""
        return _read_client_entry(db_path, mw)

    # ── Tool: run_full_probe ───────────────────────────────────────────

    @server.tool(
        description=(
            "Run a comprehensive capability probe. For best results, "
            "read the probe://status resource before calling this tool. "
            "Sends list-changed notifications to test listChanged support, "
            "then issues server-to-client requests for roots, sampling, "
            "and elicitation. Note: sampling triggers a lightweight LLM "
            "call; elicitation shows a confirmation dialog to the user."
        ),
    )
    async def run_full_probe(ctx: Context) -> dict[str, Any]:  # pragma: no cover — requires live MCP session
        """Execute all probing tiers and return the full result."""
        return await _run_deep_probe(ctx, mw)

    # ── Resource (triggers resources/list observation) ─────────────────

    @server.resource(
        "probe://status",
        description="Current probe status and captured capabilities.",
    )
    def probe_status() -> str:
        """Return probe status as a resource."""
        entry = _read_client_entry(db_path, mw)
        if not entry:  # pragma: no cover — middleware _flush creates entry before handler
            return "No capabilities captured yet."
        return json.dumps(entry, indent=2)

    # ── Prompt (triggers prompts/list observation) ─────────────────────

    @server.prompt(
        description="Summarise the capabilities captured by the probe server.",
    )
    def probe_summary() -> str:
        """Return a formatted summary of captured capabilities."""
        entry = _read_client_entry(db_path, mw)
        if not entry:  # pragma: no cover — middleware _flush creates entry before handler
            return "No capabilities captured yet. Connect an MCP client to begin probing."
        name = entry.get("clientInfo", {}).get("name", "Unknown")
        return f"Probe results for {name}:\n\n```json\n{json.dumps(entry, indent=2)}\n```"

    return server


# Module-level server instance for ``fastmcp install`` auto-discovery.
# Uses the MCP_PROBE_DB env var (falls back to ~/mcp-probes/mcp-clients-2026.json).
server = _build_server(Path(os.environ.get("MCP_PROBE_DB", _DEFAULT_DB)).resolve())


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        prog="mcp-probe",
        description=("MCP capability probe server — connects via stdio and captures client capabilities through passive and active probing."),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("MCP_PROBE_DB", _DEFAULT_DB),
        metavar="FILE",
        help=(f"Path to probe database file (default: {_DEFAULT_DB!r}, env: MCP_PROBE_DB)"),
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    srv = _build_server(db_path)
    srv.run(transport="stdio")


if __name__ == "__main__":
    main()
