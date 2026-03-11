#!/usr/bin/env python3
"""Generate a GitHub Pages site with a merged MCP client capabilities table.

Reads both ``mcp-clients.json`` (community baseline) and
``mcp-clients-2026.json`` (probe-verified data) to produce a single rich
HTML table using great-tables.

Usage:
    uv run --group site python scripts/generate-site.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import polars as pl
from great_tables import GT, loc, md, style

_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_PATH = _ROOT / "src" / "mcp_client_capabilities" / "mcp-clients.json"
_PROBED_PATH = _ROOT / "src" / "mcp_client_capabilities" / "mcp-clients-2026.json"
_SITE_DIR = _ROOT / "site"

_CAPS = ["resources", "prompts", "tools", "sampling", "roots", "elicitation"]
_LC_CAPS = {"tools", "resources", "prompts"}

_VERIFIED_ICON = '<span data-tip="Verified by MCP probe server" style="cursor:help">✔</span>'

# Friendly overrides for probe-only clients that report bundle IDs as names
_PROBE_OVERRIDES: dict[str, dict[str, str]] = {
    "dev.warp.Warp-Preview": {"title": "Warp Preview", "url": "https://www.warp.dev/download-preview"},
}


def _icon(supported: bool | None, *, probed: bool, lc: bool | None = None) -> str:
    """Return a styled icon string for a capability cell."""
    if supported is True:
        tip = "Supported (probe-verified)" if probed else "Supported (community-reported, unverified)"
        icon = "✅"
    elif supported is False:
        tip = "Not supported (probe-verified)" if probed else "Not supported (community-reported, unverified)"
        icon = "❌"
    else:
        tip = "Unknown / not tested"
        icon = "—"

    # Dim unverified values
    opacity = "opacity:0.4;" if not probed and supported is not None else ""
    base = f'<span data-tip="{tip}" style="{opacity}cursor:help">{icon}</span>'

    # listChanged badge (stacked below icon)
    lc_style = "font-size:0.6em;padding:1px 4px;border-radius:3px;font-weight:700;cursor:help"
    if lc is True:
        base += f'<br><span data-tip="listChanged: supported \u2014 client re-lists after notification" style="background:#dcfce7;color:#166534;{lc_style}">LC</span>'
    elif lc is False:
        base += f'<br><span data-tip="listChanged: not supported \u2014 client ignores notifications" style="background:#fee2e2;color:#991b1b;{lc_style}">LC</span>'

    return base


def _format_timestamp(iso: str) -> str:
    """Format an ISO timestamp to a short readable string."""
    if not iso:
        return ""
    # "2026-03-11T16:01:52.645815+00:00" -> "2026-03-11 16:01 UTC"
    try:
        date, rest = iso.split("T", 1)
        time = rest[:5]  # HH:MM
    except (ValueError, IndexError):
        return iso[:16]
    else:
        return f'{date} {time} <span style="font-size:0.8em;color:#9ca3af">UTC</span>'


def _build_dataframe(baseline: dict, probed: dict) -> pl.DataFrame:
    """Merge baseline and probed data into a polars DataFrame."""
    probed_by_title: dict[str, dict] = {}
    for entry in probed.values():
        title = entry.get("clientRecord", {}).get("title", "")
        if title:
            probed_by_title[title] = entry

    seen_titles: set[str] = set()
    seen_keys: set[str] = set()
    rows: list[dict] = []

    # Process baseline clients
    for key, bl in sorted(baseline.items(), key=lambda kv: kv[1].get("title", kv[0]).lower()):
        title = bl.get("title", key)
        if title in seen_titles:
            continue
        seen_titles.add(title)
        seen_keys.add(key)

        probe = probed.get(key) or probed_by_title.get(title)
        is_probed = probe is not None
        url = bl.get("url", "")

        row: dict = {
            "client": f'<a href="{html.escape(url, quote=True)}" target="_blank">{html.escape(title)}</a>' if url else html.escape(title),
            "protocol": bl.get("protocolVersion", ""),
            "verified": _VERIFIED_ICON if is_probed else "",
            "last_checked": _format_timestamp(probe.get("capturedAt", "")) if probe else "",
        }

        for cap in _CAPS:
            bl_has = cap in bl
            if probe:
                pcap = probe.get("capabilities", {}).get(cap, {})
                pval = pcap.get("supported")
                lc = pcap.get("listChanged") if cap in _LC_CAPS else None
                # Use probe value when available, fall back to baseline
                supported = pval if pval is not None else bl_has
                actually_probed = pval is not None
                row[cap] = _icon(supported, probed=actually_probed, lc=lc)
            else:
                row[cap] = _icon(bl_has, probed=False)

        rows.append(row)

    # Add probe-only clients (not in baseline)
    for key, probe in probed.items():
        if key in seen_keys:
            continue
        override = _PROBE_OVERRIDES.get(key, {})
        title = override.get("title") or probe.get("clientRecord", {}).get("title", key)
        if title in seen_titles:
            continue
        seen_titles.add(title)
        seen_keys.add(key)
        url = override.get("url") or probe.get("clientRecord", {}).get("url", "")
        row = {
            "client": f'<a href="{html.escape(url, quote=True)}" target="_blank">{html.escape(title)}</a>' if url else html.escape(title),
            "protocol": probe.get("protocolVersion", ""),
            "verified": _VERIFIED_ICON,
            "last_checked": _format_timestamp(probe.get("capturedAt", "")),
        }
        for cap in _CAPS:
            pcap = probe.get("capabilities", {}).get(cap, {})
            lc = pcap.get("listChanged") if cap in _LC_CAPS else None
            row[cap] = _icon(pcap.get("supported"), probed=True, lc=lc)
        rows.append(row)

    return pl.DataFrame(rows)


def _build_table(df: pl.DataFrame) -> GT:
    """Build a Great Tables table from the merged DataFrame."""
    return (
        GT(df, id="mcp-caps")
        .tab_header(
            title=md("**MCP Client Capabilities**"),
            subtitle="Hover any icon for details. Data merged from community reports and probe-verified results.",
        )
        .tab_source_note(
            md(
                "Data: [mcp-clients.json](https://github.com/nicobailon/mcp-client-capabilities/blob/main/src/mcp_client_capabilities/mcp-clients.json)"
                " + [mcp-clients-2026.json](https://github.com/nicobailon/mcp-client-capabilities/blob/main/src/mcp_client_capabilities/mcp-clients-2026.json)"
                " · [GitHub](https://github.com/nicobailon/mcp-client-capabilities)"
            )
        )
        .cols_label(
            client="Client",
            protocol="Protocol",
            verified="Verified",
            last_checked="Last Checked",
            resources="Resources",
            prompts="Prompts",
            tools="Tools",
            sampling="Sampling",
            roots="Roots",
            elicitation="Elicitation",
        )
        .cols_align(align="center", columns=["verified", "last_checked", *_CAPS])
        .cols_align(align="left", columns=["client"])
        .cols_align(align="center", columns=["protocol"])
        .cols_width(
            client="220px",
            protocol="110px",
            verified="70px",
            last_checked="140px",
        )
        .fmt_markdown(columns=["last_checked", *_CAPS])
        .tab_options(
            heading_title_font_size="24px",
            heading_subtitle_font_size="13px",
            column_labels_font_size="13px",
            column_labels_font_weight="bold",
            source_notes_font_size="11px",
            table_font_size="15px",
            data_row_padding="5px",
            table_width="100%",
        )
        .tab_style(
            style=style.text(font="ui-monospace, monospace", size="12px", color="#6b7280"),
            locations=loc.body(columns="protocol"),
        )
        .tab_style(
            style=style.fill(color="#f0fdf4"),
            locations=loc.body(rows=pl.col("verified") != ""),
        )
    )


def _wrap_page(table_html: str, client_count: int) -> str:
    """Wrap the GT table HTML in a full page with header and styling."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCP Client Capabilities</title>
  <style>
    html {{ overflow-y: scroll; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 2rem;
      background: #fafafa;
      color: #1f2937;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    #mcp-caps a {{ color: #2563eb; text-decoration: none; }}
    #mcp-caps a:hover {{ text-decoration: underline; }}
    .filters {{
      display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; align-items: center;
    }}
    .filters input[type="text"] {{
      border: 1px solid #d1d5db; border-radius: 6px; padding: 0.4rem 0.75rem;
      font-size: 0.9rem; width: 220px; outline: none;
    }}
    .filters input[type="text"]:focus {{ border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,0.15); }}
    .filters label {{
      font-size: 0.85rem; color: #374151; display: inline-flex; align-items: center;
      gap: 0.25rem; cursor: pointer; user-select: none;
    }}
    .sep {{ width: 1px; height: 1.5rem; background: #d1d5db; margin: 0 0.25rem; }}
    .pill {{
      font-size: 0.8rem; padding: 0.25rem 0.6rem; border-radius: 999px;
      border: 1px solid #d1d5db; background: white; color: #374151;
      cursor: pointer; user-select: none; transition: all 0.15s;
    }}
    .pill:hover {{ border-color: #9ca3af; }}
    .pill.active {{ background: #2563eb; color: white; border-color: #2563eb; }}
    #mcp-caps .gt_col_heading {{ cursor: pointer; user-select: none; white-space: nowrap; }}
    #mcp-caps .gt_col_heading:hover {{ background: #f3f4f6; }}
    .sort-arrow {{ font-size: 0.7em; margin-left: 2px; color: #9ca3af; }}
    #tip {{
      position: fixed; padding: 5px 10px; border-radius: 5px;
      background: #1f2937; color: #fff; font-size: 12px; white-space: nowrap;
      pointer-events: none; z-index: 9999; display: none;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="filters">
      <input type="text" id="search" placeholder="Filter clients\u2026" oninput="applyFilters()">
      <label><input type="checkbox" id="verified-only" onchange="applyFilters()"> Verified only</label>
      <div class="sep"></div>
      <span class="pill" data-col="4" onclick="togglePill(this)">Resources</span>
      <span class="pill" data-col="5" onclick="togglePill(this)">Prompts</span>
      <span class="pill" data-col="6" onclick="togglePill(this)">Tools</span>
      <span class="pill" data-col="7" onclick="togglePill(this)">Sampling</span>
      <span class="pill" data-col="8" onclick="togglePill(this)">Roots</span>
      <span class="pill" data-col="9" onclick="togglePill(this)">Elicitation</span>
      <span id="count" style="font-size:0.85rem;color:#6b7280;margin-left:0.25rem">{client_count} clients</span>
    </div>
    {table_html}
  </div>
  <div id="tip"></div>
  <script>
    function togglePill(el) {{
      el.classList.toggle('active');
      applyFilters();
    }}
    function applyFilters() {{
      const q = document.getElementById('search').value.toLowerCase();
      const vo = document.getElementById('verified-only').checked;
      const activePills = [...document.querySelectorAll('.pill.active')].map(p => parseInt(p.dataset.col));
      const rows = document.querySelectorAll('#mcp-caps .gt_table_body tr');
      let visible = 0;
      rows.forEach(row => {{
        const cells = row.querySelectorAll('td');
        if (!cells.length) return;
        const name = (cells[0] || {{}}).textContent.toLowerCase();
        const isVerified = (cells[2] || {{}}).textContent.trim() !== '';
        let show = name.includes(q);
        if (vo && !isVerified) show = false;
        if (show && activePills.length) {{
          show = activePills.every(col => {{
            const cell = cells[col];
            return cell && cell.textContent.includes('\u2705');
          }});
        }}
        row.style.display = show ? '' : 'none';
        if (show) visible++;
      }});
      document.getElementById('count').textContent = visible + ' / ' + rows.length;
    }}
    applyFilters();

    // Column sorting
    let sortCol = -1, sortAsc = true;
    function sortTable(colIdx) {{
      const tbody = document.querySelector('#mcp-caps .gt_table_body');
      const rows = [...tbody.querySelectorAll('tr')];
      if (sortCol === colIdx) {{ sortAsc = !sortAsc; }} else {{ sortCol = colIdx; sortAsc = true; }}
      rows.sort((a, b) => {{
        const at = (a.children[colIdx] || {{}}).textContent.trim();
        const bt = (b.children[colIdx] || {{}}).textContent.trim();
        const cmp = at.localeCompare(bt, undefined, {{numeric: true, sensitivity: 'base'}});
        return sortAsc ? cmp : -cmp;
      }});
      rows.forEach(r => tbody.appendChild(r));
      document.querySelectorAll('#mcp-caps .gt_col_heading .sort-arrow').forEach(el => el.textContent = '');
      const th = document.querySelectorAll('#mcp-caps .gt_col_heading')[colIdx];
      if (th) {{
        let arrow = th.querySelector('.sort-arrow');
        if (!arrow) {{ arrow = document.createElement('span'); arrow.className = 'sort-arrow'; th.appendChild(arrow); }}
        arrow.textContent = sortAsc ? ' \u25b2' : ' \u25bc';
      }}
      applyFilters();
    }}
    document.querySelectorAll('#mcp-caps .gt_col_heading').forEach((th, i) => {{
      th.addEventListener('click', () => sortTable(i));
    }});

    const tip = document.getElementById('tip');
    document.addEventListener('mouseover', e => {{
      const el = e.target.closest('[data-tip]');
      if (!el) {{ tip.style.display = 'none'; return; }}
      tip.textContent = el.dataset.tip;
      tip.style.display = 'block';
      const r = el.getBoundingClientRect();
      tip.style.left = (r.left + r.width / 2 - tip.offsetWidth / 2) + 'px';
      tip.style.top = (r.top - tip.offsetHeight - 6) + 'px';
    }});
    document.addEventListener('mouseout', e => {{
      if (e.target.closest('[data-tip]')) tip.style.display = 'none';
    }});
  </script>
</body>
</html>"""


def main() -> None:
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8")) if _BASELINE_PATH.exists() else {}
    probed = json.loads(_PROBED_PATH.read_text(encoding="utf-8")) if _PROBED_PATH.exists() else {}

    if not baseline and not probed:
        print("No data files found")
        return

    df = _build_dataframe(baseline, probed)
    gt = _build_table(df)

    _SITE_DIR.mkdir(exist_ok=True)
    table_html = gt.as_raw_html()
    page_html = _wrap_page(table_html, len(df))
    (_SITE_DIR / "index.html").write_text(page_html, encoding="utf-8")
    print(f"Site generated: {_SITE_DIR / 'index.html'} ({len(df)} clients)")


if __name__ == "__main__":
    main()
