"""Tests for _CapabilityCaptureMW state machine and output format.

These tests exercise the middleware's build methods directly by
manipulating internal state, avoiding the need for a real MCP connection.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from mcp.types import TextContent

from mcp_client_capabilities import probe_server
from mcp_client_capabilities.probe_server import _build_server, _CapabilityCaptureMW, _read_client_entry
from tests.conftest import read_client_entry

# ---------------------------------------------------------------------------
# _build_capability_detail — three-state logic
# ---------------------------------------------------------------------------


class TestBuildCapabilityDetail:
    """Test the three-state (True/False/None) capability detail builder."""

    def test_untested_non_listable_returns_none_supported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        detail = mw._build_capability_detail("roots")
        assert detail["supported"] is None
        assert detail["evidence"] == "not tested"

    def test_untested_listable_returns_false(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        detail = mw._build_capability_detail("tools")
        assert detail["supported"] is False
        assert "server advertised tools" in detail["evidence"]

    def test_observed_marks_supported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        detail = mw._build_capability_detail("tools")
        assert detail["supported"] is True
        assert "client called tools/list" in detail["evidence"]

    def test_declared_marks_supported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._declared["roots"] = {"listChanged": True}
        detail = mw._build_capability_detail("roots")
        assert detail["supported"] is True
        assert "declared in initialize handshake" in detail["evidence"]

    def test_active_true_marks_supported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._active["roots"] = True
        mw._active_evidence["roots"] = "list_roots returned 1 root(s)"
        detail = mw._build_capability_detail("roots")
        assert detail["supported"] is True
        assert "list_roots returned 1 root(s)" in detail["evidence"]

    def test_active_false_marks_not_supported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._active["sampling"] = False
        mw._active_evidence["sampling"] = "sampling request failed: McpError"
        detail = mw._build_capability_detail("sampling")
        assert detail["supported"] is False
        assert "McpError" in detail["evidence"]

    def test_active_false_overrides_declared(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._declared["roots"] = {}
        mw._active["roots"] = False
        mw._active_evidence["roots"] = "list_roots request failed: TimeoutError"
        detail = mw._build_capability_detail("roots")
        assert detail["supported"] is False

    def test_list_changed_included_when_tested(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        mw._list_changed["tools"] = True
        mw._list_changed_evidence["tools"] = "listChanged: sent notification, client re-listed within 5s"
        detail = mw._build_capability_detail("tools")
        assert detail["listChanged"] is True
        assert "re-listed within 5s" in detail["evidence"]

    def test_list_changed_none_when_supported_but_untested(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["prompts"] = ["prompts/list"]
        detail = mw._build_capability_detail("prompts")
        assert detail["listChanged"] is None

    def test_list_changed_absent_for_non_listable(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._active["roots"] = True
        mw._active_evidence["roots"] = "list_roots returned 2 root(s)"
        detail = mw._build_capability_detail("roots")
        assert "listChanged" not in detail

    def test_multiple_observed_methods_joined(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["resources"] = ["resources/list", "resources/read"]
        detail = mw._build_capability_detail("resources")
        assert "resources/list, resources/read" in detail["evidence"]

    def test_evidence_combines_declared_and_observed(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._declared["roots"] = {}
        mw._active["roots"] = True
        mw._active_evidence["roots"] = "list_roots returned 3 root(s)"
        detail = mw._build_capability_detail("roots")
        assert "declared in initialize handshake" in detail["evidence"]
        assert "list_roots returned 3 root(s)" in detail["evidence"]

    def test_unknown_non_listable_key_returns_none(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        detail = mw._build_capability_detail("nonexistent")
        assert detail["supported"] is None
        assert detail["evidence"] == "not tested"

    def test_declared_but_actively_unsupported(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        """Active False should override declared, evidence should mention both."""
        mw._declared["roots"] = {"listChanged": True}
        mw._active["roots"] = False
        mw._active_evidence["roots"] = "list_roots request failed: TimeoutError"
        detail = mw._build_capability_detail("roots")
        assert detail["supported"] is False
        assert "declared in initialize handshake" in detail["evidence"]
        assert "TimeoutError" in detail["evidence"]

    def test_list_changed_false_still_included(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        """listChanged=False should appear in the detail dict."""
        mw._observed["tools"] = ["tools/list"]
        mw._list_changed["tools"] = False
        mw._list_changed_evidence["tools"] = "listChanged: sent notification, client did not re-list within 5s"
        detail = mw._build_capability_detail("tools")
        assert detail["listChanged"] is False
        assert "did not re-list" in detail["evidence"]


# ---------------------------------------------------------------------------
# _build_client_record — mcp-clients.json compatible output
# ---------------------------------------------------------------------------


class TestBuildClientRecord:
    """Test the clientRecord output matches mcp-clients.json convention."""

    def test_empty_state_has_required_keys(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        record = mw._build_client_record()
        assert "protocolVersion" in record
        assert "title" in record
        assert "url" in record

    def test_only_supported_capabilities_included(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        mw._active["roots"] = False
        record = mw._build_client_record()
        assert "tools" in record
        assert "roots" not in record
        assert "resources" not in record

    def test_list_changed_only_when_true(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        mw._list_changed["tools"] = False
        record = mw._build_client_record()
        assert record["tools"] == {}

    def test_list_changed_true_included(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        mw._list_changed["tools"] = True
        record = mw._build_client_record()
        assert record["tools"] == {"listChanged": True}

    def test_title_from_client_info(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._client_info = {"name": "TestClient", "version": "1.0"}
        record = mw._build_client_record()
        assert record["title"] == "TestClient"

    def test_experimental_forwarded(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._declared["experimental"] = {"customFeature": True}
        record = mw._build_client_record()
        assert record["experimental"] == {"customFeature": True}

    def test_declared_but_actively_unsupported_excluded(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        """Capability declared in handshake but actively disproven should be excluded."""
        mw._declared["roots"] = {}
        mw._active["roots"] = False
        mw._active_evidence["roots"] = "list_roots request failed: TimeoutError"
        record = mw._build_client_record()
        assert "roots" not in record

    def test_list_changed_none_not_in_record(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        """Untested listChanged (None) should not appear in clientRecord."""
        mw._observed["prompts"] = ["prompts/list"]
        record = mw._build_client_record()
        assert "prompts" in record
        assert "listChanged" not in record["prompts"]


# ---------------------------------------------------------------------------
# _build_result — full probe output
# ---------------------------------------------------------------------------


class TestBuildResult:
    """Test the full probe result structure."""

    def test_top_level_keys(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        assert "capturedAt" in result
        assert "clientInfo" in result
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "clientRecord" in result

    def test_all_capabilities_present(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        caps = result["capabilities"]
        for key in mw._ALL_CAPS:
            assert key in caps, f"missing capability: {key}"

    def test_each_capability_has_supported_and_evidence(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        for key, detail in result["capabilities"].items():
            assert "supported" in detail, f"{key} missing 'supported'"
            assert "evidence" in detail, f"{key} missing 'evidence'"

    def test_result_is_json_serializable(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        serialized = json.dumps(result, indent=2, default=str)
        parsed = json.loads(serialized)
        assert parsed["capabilities"]["tools"]["supported"] is False

    def test_captured_at_is_valid_iso_timestamp(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        ts = result["capturedAt"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.year >= 2025

    def test_all_caps_covers_expected_capabilities(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        expected = {"tools", "resources", "prompts", "roots", "sampling", "elicitation", "completions", "logging"}
        assert set(mw._ALL_CAPS) == expected

    def test_experimental_in_result_when_declared(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._declared["experimental"] = {"someFeature": True}
        result = mw._build_result()
        assert "experimental" in result["capabilities"]
        assert result["capabilities"]["experimental"]["supported"] is True

    def test_experimental_absent_when_not_declared(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._build_result()
        assert "experimental" not in result["capabilities"]


# ---------------------------------------------------------------------------
# _observe — method tracking
# ---------------------------------------------------------------------------


class TestObserve:
    """Test the observation tracking logic."""

    def test_first_observe_creates_entry(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observe("tools", "tools/list", "client listed tools")
        assert "tools" in mw._observed
        assert mw._observed["tools"] == ["tools/list"]

    def test_duplicate_method_not_added(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observe("tools", "tools/list", "listed")
        mw._observe("tools", "tools/list", "listed again")
        assert mw._observed["tools"] == ["tools/list"]

    def test_different_methods_tracked(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observe("resources", "resources/list", "listed")
        mw._observe("resources", "resources/read", "read")
        assert mw._observed["resources"] == ["resources/list", "resources/read"]

    def test_first_observe_triggers_flush(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        assert not tmp_output.exists()
        mw._observe("tools", "tools/list", "listed")
        assert tmp_output.exists()

    def test_second_observe_same_capability_does_not_flush(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        mw._observe("tools", "tools/list", "listed")
        content_after_first = tmp_output.read_text(encoding="utf-8")
        mw._observe("tools", "tools/call", "called")
        assert tmp_output.read_text(encoding="utf-8") == content_after_first

    def test_second_different_capability_triggers_flush(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        mw._observe("tools", "tools/list", "listed tools")
        content_after_tools = tmp_output.read_text(encoding="utf-8")
        mw._observe("resources", "resources/list", "listed resources")
        content_after_resources = tmp_output.read_text(encoding="utf-8")
        assert content_after_resources != content_after_tools
        data = read_client_entry(tmp_output)
        assert data["capabilities"]["resources"]["supported"] is True


# ---------------------------------------------------------------------------
# _flush — file writing
# ---------------------------------------------------------------------------


class TestFlush:
    """Test that _flush writes valid JSON to disk."""

    def test_flush_creates_file(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        mw._flush()
        assert tmp_output.exists()

    def test_flush_writes_valid_json(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        mw._flush()
        data = read_client_entry(tmp_output)
        assert "capabilities" in data
        assert "clientRecord" in data

    def test_successive_flushes_update_file(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        mw._flush()
        first = read_client_entry(tmp_output)
        assert first["capabilities"]["tools"]["supported"] is False

        mw._observed["tools"] = ["tools/list"]
        mw._flush()
        second = read_client_entry(tmp_output)
        assert second["capabilities"]["tools"]["supported"] is True

    def test_flush_survives_unwritable_path(self) -> None:
        mw = _CapabilityCaptureMW(Path("/nonexistent/dir/out.json"))
        mw._flush()  # should not raise

    def test_flush_recovers_from_corrupted_json(self, tmp_output: Path) -> None:
        """Regression: _flush must recover from corrupted DB by starting fresh."""
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_text("{invalid json", encoding="utf-8")
        mw = _CapabilityCaptureMW(tmp_output)
        mw._flush()  # should not raise
        # File should now contain valid JSON with the new entry
        data = json.loads(tmp_output.read_text(encoding="utf-8"))
        assert "unknown" in data
        assert "capabilities" in data["unknown"]


# ---------------------------------------------------------------------------
# Integration: realistic scenario
# ---------------------------------------------------------------------------


class TestRealisticScenario:
    """Simulate a realistic Windsurf-like probe session."""

    def test_windsurf_like_session(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        # Handshake: client declares roots
        mw._client_info = {"name": "Windsurf", "version": "1.0.0"}
        mw._protocol_version = "2025-11-25"

        # Client lists tools and prompts but not resources
        mw._observe("tools", "tools/list", "listed tools")
        mw._observe("prompts", "prompts/list", "listed prompts")

        # listChanged tested — client doesn't re-list
        mw._list_changed["tools"] = False
        mw._list_changed_evidence["tools"] = "listChanged: sent notification, client did not re-list within 5s"
        mw._list_changed["prompts"] = False
        mw._list_changed_evidence["prompts"] = "listChanged: sent notification, client did not re-list within 5s"

        # Server→client probes: all fail
        for key in ("roots", "sampling", "elicitation"):
            mw._active[key] = False
            mw._active_evidence[key] = f"{key} request failed: McpError"

        mw._flush()
        data = read_client_entry(tmp_output, "Windsurf")

        # capabilities section
        caps = data["capabilities"]
        assert caps["tools"]["supported"] is True
        assert caps["tools"]["listChanged"] is False
        assert caps["prompts"]["supported"] is True
        assert caps["resources"]["supported"] is False
        assert caps["roots"]["supported"] is False
        assert caps["sampling"]["supported"] is False
        assert caps["elicitation"]["supported"] is False
        assert caps["completions"]["supported"] is None
        assert caps["logging"]["supported"] is None

        # clientRecord section
        rec = data["clientRecord"]
        assert rec["title"] == "Windsurf"
        assert "tools" in rec
        assert "prompts" in rec
        assert "resources" not in rec
        assert "roots" not in rec

        # comparison sections present
        assert "comparisonVsDatabase" in data
        assert "comparisonVsPreviousProbe" in data

    def test_full_support_session(
        self,
        mw: _CapabilityCaptureMW,
        tmp_output: Path,
    ) -> None:
        """Simulate a client that supports everything."""
        mw._client_info = {"name": "FullClient", "version": "2.0"}
        mw._protocol_version = "2025-03-26"
        mw._declared["roots"] = {"listChanged": True}
        mw._declared["sampling"] = {}
        mw._declared["elicitation"] = {}

        mw._observe("tools", "tools/list", "listed")
        mw._observe("resources", "resources/list", "listed")
        mw._observe("prompts", "prompts/list", "listed")

        mw._list_changed["tools"] = True
        mw._list_changed_evidence["tools"] = "listChanged: sent notification, client re-listed within 5s"

        mw._active["roots"] = True
        mw._active_evidence["roots"] = "list_roots returned 2 root(s)"
        mw._active["sampling"] = True
        mw._active_evidence["sampling"] = "sampling request returned: 'probe-ok'"
        mw._active["elicitation"] = True
        mw._active_evidence["elicitation"] = "elicitation request returned: action=accept"

        mw._flush()
        data = read_client_entry(tmp_output, "FullClient")

        caps = data["capabilities"]
        assert all(caps[k]["supported"] is True for k in ("tools", "resources", "prompts", "roots", "sampling", "elicitation"))
        assert caps["tools"]["listChanged"] is True

        rec = data["clientRecord"]
        assert rec["tools"] == {"listChanged": True}
        assert rec["resources"] == {}
        assert rec["roots"] == {}
        assert rec["sampling"] == {}


# ---------------------------------------------------------------------------
# _compare_vs_database — probe vs mcp-clients.json
# ---------------------------------------------------------------------------


class TestCompareVsDatabase:
    """Test comparison of probe results against the existing mcp-clients.json."""

    def test_new_client_not_in_database(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._client_info = {"name": "BrandNewClient"}
        result = mw._compare_vs_database("BrandNewClient")
        assert result["status"] == "new_client"

    def test_match_when_capabilities_agree(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        # claude-ai exists in mcp-clients.json with tools, resources, prompts
        mw._client_info = {"name": "claude-ai"}
        mw._protocol_version = "2025-06-18"
        mw._observed["tools"] = ["tools/list"]
        mw._observed["resources"] = ["resources/list"]
        mw._observed["prompts"] = ["prompts/list"]
        result = mw._compare_vs_database("claude-ai")
        assert result["status"] == "match"

    def test_has_discrepancies_when_capabilities_differ(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        # claude-ai has tools in DB, but probe says no tools
        mw._client_info = {"name": "claude-ai"}
        mw._protocol_version = "2025-06-18"
        # Don't observe tools → they won't be in clientRecord
        result = mw._compare_vs_database("claude-ai")
        assert result["status"] == "has_discrepancies"
        caps_with_discrep = [d["capability"] for d in result["discrepancies"]]
        assert "tools" in caps_with_discrep

    def test_protocol_version_discrepancy(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._client_info = {"name": "claude-ai"}
        mw._protocol_version = "9999-01-01"
        mw._observed["tools"] = ["tools/list"]
        mw._observed["resources"] = ["resources/list"]
        mw._observed["prompts"] = ["prompts/list"]
        result = mw._compare_vs_database("claude-ai")
        assert result["status"] == "has_discrepancies"
        pv = [d for d in result["discrepancies"] if d["capability"] == "protocolVersion"]
        assert len(pv) == 1
        assert pv[0]["probe"] == "9999-01-01"

    def test_error_when_json_unreadable(
        self,
        mw: _CapabilityCaptureMW,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(probe_server, "_KNOWN_CLIENTS_PATH", Path("/nonexistent/file.json"))
        result = mw._compare_vs_database("anything")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# _compare_vs_previous — probe vs previous probe in DB
# ---------------------------------------------------------------------------


class TestCompareVsPrevious:
    """Test comparison of current probe against the previous probe in the DB."""

    def test_first_probe_when_no_previous(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        result = mw._compare_vs_previous()
        assert result["status"] == "first_probe"

    def test_no_changes_when_same(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        mw._observed["tools"] = ["tools/list"]
        mw._previous_probe = {
            "clientRecord": {"tools": {}},
        }
        result = mw._compare_vs_previous()
        assert result["status"] == "no_changes"

    def test_has_changes_when_different(
        self,
        mw: _CapabilityCaptureMW,
    ) -> None:
        # Previous had tools, current doesn't
        mw._previous_probe = {
            "clientRecord": {"tools": {}, "resources": {}},
        }
        result = mw._compare_vs_previous()
        assert result["status"] == "has_changes"
        caps = [c["capability"] for c in result["changes"]]
        assert "tools" in caps
        assert "resources" in caps


# ---------------------------------------------------------------------------
# DB upsert — unknown→named re-keying
# ---------------------------------------------------------------------------


class TestDbUpsert:
    """Test DB file upsert and client re-keying."""

    def test_unknown_entry_deleted_when_name_known(
        self,
        tmp_output: Path,
    ) -> None:
        # Seed DB with "unknown" entry
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_text('{"unknown": {"old": true}}', encoding="utf-8")

        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "MyClient"}
        mw._flush()

        db = json.loads(tmp_output.read_text(encoding="utf-8"))
        assert "unknown" not in db
        assert "MyClient" in db

    def test_previous_probe_snapshot_loaded_once(
        self,
        tmp_output: Path,
    ) -> None:
        # Seed DB with previous entry for "TestClient"
        prev = {"clientRecord": {"tools": {}}, "capabilities": {}}
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_text(json.dumps({"TestClient": prev}), encoding="utf-8")

        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "TestClient"}
        mw._flush()

        # Previous was loaded
        assert mw._previous_loaded is True
        assert mw._previous_probe is not None
        assert mw._previous_probe["clientRecord"]["tools"] == {}

    def test_multiple_clients_coexist(
        self,
        tmp_output: Path,
    ) -> None:
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_text('{"ClientA": {"old": true}}', encoding="utf-8")

        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "ClientB"}
        mw._flush()

        db = json.loads(tmp_output.read_text(encoding="utf-8"))
        assert "ClientA" in db
        assert "ClientB" in db


# ---------------------------------------------------------------------------
# Null-merge — never regress non-null → null
# ---------------------------------------------------------------------------


class TestNullMerge:
    """Test that untested (null) capabilities don't overwrite known values."""

    def _seed_previous(self, tmp_output: Path, caps: dict, *, client_record: dict | None = None) -> None:
        prev = {"capabilities": caps, "clientRecord": client_record or {"protocolVersion": "", "title": "X", "url": ""}}
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_text(json.dumps({"X": prev}), encoding="utf-8")

    def test_null_does_not_overwrite_previous_true(self, tmp_output: Path) -> None:
        self._seed_previous(tmp_output, {"roots": {"supported": True, "evidence": "deep probe"}})
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        # roots stays untested (null) in current probe
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        assert entry["capabilities"]["roots"]["supported"] is True
        assert entry["capabilities"]["roots"]["evidence"] == "deep probe"

    def test_null_does_not_overwrite_previous_false(self, tmp_output: Path) -> None:
        self._seed_previous(tmp_output, {"sampling": {"supported": False, "evidence": "failed"}})
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        assert entry["capabilities"]["sampling"]["supported"] is False

    def test_non_null_does_overwrite_previous(self, tmp_output: Path) -> None:
        self._seed_previous(tmp_output, {"roots": {"supported": False, "evidence": "old"}})
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        mw._active["roots"] = True
        mw._active_evidence["roots"] = "list_roots returned 1 root(s)"
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        assert entry["capabilities"]["roots"]["supported"] is True

    def test_null_merge_updates_client_record(self, tmp_output: Path) -> None:
        """Regression: clientRecord must reflect null-merged capabilities."""
        self._seed_previous(tmp_output, {"roots": {"supported": True, "evidence": "deep probe"}})
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        # roots stays untested (null) in current probe → merge preserves True
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        assert entry["capabilities"]["roots"]["supported"] is True
        # clientRecord must also include roots (since it's supported after merge)
        assert "roots" in entry["clientRecord"]

    def test_null_merge_comparisons_use_merged_record(self, tmp_output: Path) -> None:
        """Regression: comparisons must reflect null-merged capabilities, not raw state."""
        prev_caps = {"roots": {"supported": True, "evidence": "deep probe"}}
        prev_record = {"protocolVersion": "", "title": "X", "url": "", "roots": {}}
        self._seed_previous(tmp_output, prev_caps, client_record=prev_record)
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        # roots stays untested → merge preserves True
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        # comparisonVsPreviousProbe should NOT report roots as changed
        cmp = entry["comparisonVsPreviousProbe"]
        if cmp["status"] == "has_changes":
            changed_caps = [c["capability"] for c in cmp["changes"]]
            assert "roots" not in changed_caps, "roots was preserved by merge, should not appear as changed"

    def test_merge_preserves_multiple_caps(self, tmp_output: Path) -> None:
        self._seed_previous(
            tmp_output,
            {
                "roots": {"supported": True, "evidence": "probe"},
                "sampling": {"supported": False, "evidence": "failed"},
                "elicitation": {"supported": True, "evidence": "probe"},
            },
        )
        mw = _CapabilityCaptureMW(tmp_output)
        mw._client_info = {"name": "X"}
        # Only roots gets a new result; sampling and elicitation stay untested
        mw._active["roots"] = False
        mw._active_evidence["roots"] = "new probe failed"
        mw._flush()
        entry = read_client_entry(tmp_output, "X")
        assert entry["capabilities"]["roots"]["supported"] is False  # updated
        assert entry["capabilities"]["sampling"]["supported"] is False  # preserved
        assert entry["capabilities"]["elicitation"]["supported"] is True  # preserved


# ---------------------------------------------------------------------------
# _read_client_entry — error handling
# ---------------------------------------------------------------------------


class TestReadClientEntry:
    """Test the _read_client_entry helper."""

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path) -> None:
        mw = _CapabilityCaptureMW(tmp_path / "nope.json")
        assert _read_client_entry(tmp_path / "nope.json", mw) is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        mw = _CapabilityCaptureMW(bad)
        assert _read_client_entry(bad, mw) is None

    def test_returns_none_for_missing_client_key(self, tmp_path: Path) -> None:
        db = tmp_path / "db.json"
        db.write_text('{"other": {}}', encoding="utf-8")
        mw = _CapabilityCaptureMW(db)
        assert _read_client_entry(db, mw) is None


# ---------------------------------------------------------------------------
# _build_server — smoke test
# ---------------------------------------------------------------------------


class TestBuildServer:
    """Basic smoke test that the server constructs without errors."""

    def test_server_has_expected_name(self, tmp_output: Path) -> None:
        server = _build_server(tmp_output)
        assert server.name == "mcp-capability-probe"

    def test_instructions_mention_resource_uri(self, tmp_output: Path) -> None:
        server = _build_server(tmp_output)
        assert "probe://status" in (server.instructions or "")

    @pytest.mark.anyio
    async def test_get_probe_results_returns_none_when_no_file(self, tmp_output: Path) -> None:
        server = _build_server(tmp_output)
        tool = await server.get_tool("get_probe_results")
        assert tool is not None
        result = await tool.run({})
        assert result.structured_content == {"result": None}

    @pytest.mark.anyio
    async def test_get_probe_results_returns_data_when_file_exists(self, tmp_output: Path) -> None:
        tmp_output.write_text('{"unknown": {"test": true}}', encoding="utf-8")  # noqa: ASYNC240
        server = _build_server(tmp_output)
        tool = await server.get_tool("get_probe_results")
        assert tool is not None
        result = await tool.run({})
        sc = result.structured_content
        assert sc is not None
        assert sc["result"]["test"] is True

    @pytest.mark.anyio
    async def test_probe_status_resource_returns_json(self, tmp_output: Path) -> None:
        # Middleware on_read_resource fires first and creates the file via _flush
        server = _build_server(tmp_output)
        result = await server.read_resource("probe://status")
        content = result.contents[0].content
        assert isinstance(content, str)
        assert "capabilities" in content

    @pytest.mark.anyio
    async def test_probe_summary_prompt_returns_results(self, tmp_output: Path) -> None:
        # Middleware on_get_prompt fires first and creates the file via _flush
        server = _build_server(tmp_output)
        result = await server.render_prompt("probe_summary", {})
        texts = [m.content.text for m in result.messages if isinstance(m.content, TextContent)]
        assert any("Unknown" in t for t in texts)
