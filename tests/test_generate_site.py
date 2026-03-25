"""Regression tests for scripts/generate-site.py helper functions.

These import the helpers directly and verify edge-case behaviour
without needing to regenerate the full HTML site.
"""

from __future__ import annotations

import html
import importlib.util
from pathlib import Path

import pytest

# The script imports polars/great_tables (site dep group) — skip if missing
pytest.importorskip("polars")
pytest.importorskip("great_tables")

# Import the hyphenated script via importlib
_script = Path(__file__).resolve().parent.parent / "scripts" / "generate-site.py"
_spec = importlib.util.spec_from_file_location("generate_site", _script)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_icon = _mod._icon
_build_dataframe = _mod._build_dataframe


# ---------------------------------------------------------------------------
# _icon — probe-verified vs community-reported labelling
# ---------------------------------------------------------------------------


class TestIconProbeLabelling:
    """Regression: baseline fallback values must NOT be labelled probe-verified."""

    def test_probed_true_shows_probe_verified(self) -> None:
        result = _icon(True, probed=True)
        assert "probe-verified" in result

    def test_probed_false_shows_unverified(self) -> None:
        result = _icon(True, probed=False)
        assert "unverified" in result
        assert "probe-verified" not in result

    def test_unverified_has_opacity(self) -> None:
        result = _icon(True, probed=False)
        assert "opacity:0.4" in result

    def test_verified_has_no_opacity(self) -> None:
        result = _icon(True, probed=True)
        assert "opacity:0.4" not in result

    def test_none_supported_shows_unknown(self) -> None:
        result = _icon(None, probed=False)
        assert "Unknown" in result
        assert "opacity:0.4" not in result


# ---------------------------------------------------------------------------
# _build_dataframe — baseline fallback must NOT be labelled probe-verified
# ---------------------------------------------------------------------------


class TestBaselineFallbackLabelling:
    """Regression: when probe exists but a capability is null, fallback to
    baseline must show 'unverified', not 'probe-verified'."""

    def test_partial_probe_fallback_is_unverified(self) -> None:
        baseline = {
            "test-client": {
                "title": "Test",
                "url": "https://example.com",
                "tools": {},
                "roots": {},
            },
        }
        probed = {
            "test-client": {
                "capturedAt": "2026-01-01T00:00:00+00:00",
                "clientInfo": {"name": "test-client"},
                "protocolVersion": "2025-11-25",
                "clientRecord": {"title": "Test", "url": "https://example.com"},
                "capabilities": {
                    "tools": {"supported": True, "evidence": "observed"},
                    # roots not tested → supported: null
                    "roots": {"supported": None, "evidence": "not tested"},
                },
            },
        }
        df = _build_dataframe(baseline, probed)
        row = df.filter(df["client"].str.contains("Test")).to_dicts()[0]
        # tools was probe-verified
        assert "probe-verified" in row["tools"]
        # roots fell back to baseline → must say unverified, not probe-verified
        assert "unverified" in row["roots"]
        assert "probe-verified" not in row["roots"]


# ---------------------------------------------------------------------------
# HTML escaping — client titles and URLs must be escaped
# ---------------------------------------------------------------------------


class TestHtmlEscaping:
    """Regression: client titles/URLs with special chars must be HTML-escaped."""

    def test_title_with_angle_brackets_is_escaped(self) -> None:
        baseline = {
            "xss-client": {
                "title": '<script>alert("xss")</script>',
                "url": "https://example.com",
            },
        }
        df = _build_dataframe(baseline, {})
        cell = df.to_dicts()[0]["client"]
        assert "<script>" not in cell
        assert html.escape('<script>alert("xss")</script>') in cell

    def test_url_with_quotes_is_escaped(self) -> None:
        baseline = {
            "quote-client": {
                "title": "Normal",
                "url": 'https://example.com/foo"bar',
            },
        }
        df = _build_dataframe(baseline, {})
        cell = df.to_dicts()[0]["client"]
        assert '"bar' not in cell  # raw quote must not appear unescaped in href
        assert "&quot;" in cell
