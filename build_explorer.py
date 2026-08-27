"""
Builds a standalone, self-contained HTML data browser for the
metabolite-atlas database (metabolite_atlas.db) -> metabolite_atlas_explorer.html
 
Plain HTML/CSS/JS, no third-party branding, no network calls at runtime
(fonts load from Google Fonts over HTTPS; everything else -- data, styling,
logic -- is embedded in the single output file). Host it anywhere: GitHub
Pages, S3, a plain web server, or just open the file locally in a browser.
 
Usage:
    pip install nothing extra -- only the standard library is used
    python build_explorer.py
"""
 
import json
import re
import sqlite3
from pathlib import Path
 
DB_PATH = Path("metabolite_atlas.db")
OUT_PATH = Path("metabolite_atlas_explorer.html")
 
# ----------------------------------------------------------------------------
# The page itself: HTML + CSS + JS, with a placeholder where the exported
# JSON data gets spliced in at build time.
# ----------------------------------------------------------------------------
HTML_TEMPLATE = r"""<meta charset="utf-8">
<title>Metabolite Atlas Browser</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
  :root {
    --bg: #f5f6f8;
    --surface: #ffffff;
    --surface-2: #eef0f3;
    --ink: #14181f;
    --ink-2: #5b6472;
    --ink-3: #838d9c;
    --border: #d8dbe1;
    --accent: #2e4ae0;
    --accent-ink: #ffffff;
    --accent-soft: rgba(46, 74, 224, 0.08);
    --accent-soft-2: rgba(46, 74, 224, 0.16);
    --row-hover: rgba(46, 74, 224, 0.05);
    --shadow: 0 1px 2px rgba(20, 24, 31, 0.04), 0 8px 24px rgba(20, 24, 31, 0.05);
  }
 
  /* Defaults to light regardless of system theme (per preference). An explicit
     dark toggle from the artifact viewer, if offered, still switches it. */
  :root[data-theme="dark"] {
    --bg: #10141b;
    --surface: #171c26;
    --surface-2: #1d2330;
    --ink: #e8eaef;
    --ink-2: #9aa3b2;
    --ink-3: #6d7688;
    --border: #2b3140;
    --accent: #8296ff;
    --accent-ink: #0d1220;
    --accent-soft: rgba(130, 150, 255, 0.12);
    --accent-soft-2: rgba(130, 150, 255, 0.2);
    --row-hover: rgba(130, 150, 255, 0.08);
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 12px 32px rgba(0, 0, 0, 0.35);
  }
 
  * { box-sizing: border-box; }
 
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif;
    font-size: 15.5px;
    line-height: 1.5;
  }
 
  main {
    max-width: 1180px;
    margin: 0 auto;
    padding: 48px 24px 96px;
  }
 
  h1, h2 {
    font-family: "Fraunces", Georgia, serif;
    font-weight: 600;
    text-wrap: balance;
    margin: 0;
  }
 
  .eyebrow {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 12px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--accent);
    margin: 0 0 12px;
  }
 
  h1 { font-size: clamp(28px, 3.6vw, 38px); letter-spacing: -0.01em; }
 
  .lede {
    margin: 14px 0 0;
    max-width: 68ch;
    color: var(--ink-2);
    font-size: 16px;
  }
 
  code, .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
 
  /* stat + overview row */
  .top-grid {
    margin-top: 36px;
    display: grid;
    grid-template-columns: 1.1fr 1.4fr;
    gap: 16px;
  }
  @media (max-width: 880px) {
    .top-grid { grid-template-columns: 1fr; }
  }
 
  .stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .stat { background: var(--surface); padding: 18px; }
  .stat .n {
    font-family: "Fraunces", Georgia, serif;
    font-weight: 600;
    font-size: 26px;
    font-variant-numeric: tabular-nums;
  }
  .stat .label { margin-top: 4px; font-size: 12.5px; color: var(--ink-2); }
 
  .chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .chart-card h2 { font-size: 14.5px; font-weight: 600; font-family: "Public Sans", sans-serif; color: var(--ink-2); margin-bottom: 12px; }
  .bar-row { display: grid; grid-template-columns: 130px 1fr 52px; align-items: center; gap: 10px; padding: 4px 0; }
  .bar-row .bl { font-size: 13px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-track { height: 12px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 3px; }
  .bar-row .bn { font-size: 12px; color: var(--ink-2); text-align: right; font-variant-numeric: tabular-nums; }
 
  /* filter bar */
  .filters {
    margin-top: 28px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }
  .search-wrap { position: relative; flex: 1 1 260px; }
  .search-wrap input[type="text"] {
    width: 100%;
    padding: 10px 12px 10px 34px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--ink);
    font-size: 14px;
    font-family: inherit;
  }
  .search-wrap input[type="text"]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .search-wrap svg { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); opacity: 0.5; }
 
  select {
    padding: 10px 30px 10px 12px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--ink);
    font-size: 13.5px;
    font-family: inherit;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%235b6472' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
  }
  select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
 
  .clear-btn {
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--ink-2);
    font-size: 13.5px;
    font-family: inherit;
    cursor: pointer;
  }
  .clear-btn:hover { border-color: var(--ink-3); color: var(--ink); }
  .clear-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
 
  /* results */
  .results-head {
    margin-top: 22px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    color: var(--ink-2);
    font-size: 13.5px;
  }
  .results-head strong { color: var(--ink); font-variant-numeric: tabular-nums; }
 
  .table-card {
    margin-top: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .table-scroll { overflow-x: auto; }
  table.results { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 760px; }
  table.results th {
    text-align: left;
    padding: 10px 14px;
    background: var(--surface-2);
    color: var(--ink-2);
    font-weight: 600;
    font-size: 11.5px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  table.results td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  table.results tbody tr.data-row { cursor: pointer; }
  table.results tbody tr.data-row:hover { background: var(--row-hover); }
  table.results tbody tr:last-child td { border-bottom: none; }
  .mname { font-weight: 600; }
  .hid { color: var(--ink-3); font-size: 11.5px; display: block; margin-top: 2px; }
  .chip {
    display: inline-block;
    font-size: 11.5px;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    white-space: nowrap;
  }
  .muted { color: var(--ink-3); }
  .cite-toggle {
    background: none;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--ink-2);
    font-family: "IBM Plex Mono", monospace;
    font-size: 11px;
    padding: 4px 8px;
    cursor: pointer;
  }
  .cite-toggle:hover { border-color: var(--accent); color: var(--accent); }
  tr.cite-row td {
    background: var(--surface-2);
    font-size: 13px;
    color: var(--ink-2);
    padding: 12px 14px 14px 14px;
  }
  tr.cite-row a { color: var(--accent); }
  .empty-state { padding: 48px 20px; text-align: center; color: var(--ink-3); }
 
  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 14px;
    padding: 16px;
    border-top: 1px solid var(--border);
  }
  .pagination button {
    background: var(--surface-2);
    border: 1px solid var(--border);
    color: var(--ink);
    border-radius: 7px;
    padding: 7px 13px;
    font-size: 13px;
    font-family: inherit;
    cursor: pointer;
  }
  .pagination button:disabled { opacity: 0.4; cursor: default; }
  .pagination button:not(:disabled):hover { border-color: var(--accent); }
  .pagination .pg-info { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
 
  footer {
    margin-top: 56px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    color: var(--ink-3);
    font-size: 12.5px;
  }
</style>
 
<main>
  <p class="eyebrow">metabolite-atlas &middot; data browser</p>
  <h1>Browse the metabolite dataset</h1>
  <p class="lede">
    Search and filter the normalized HMDB concentration data without writing SQL.
    Everything below runs against the same tables shown in the
    <span class="mono">metabolite_atlas.db</span> schema &mdash; loaded once into
    this page.
  </p>
 
  <div class="top-grid">
    <div class="stats" id="stats"></div>
    <div class="chart-card">
      <h2>Measurements by biospecimen</h2>
      <div id="biospecimen-chart"></div>
    </div>
  </div>
 
  <div class="filters">
    <div class="search-wrap">
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="6.5" cy="6.5" r="5" stroke="currentColor" stroke-width="1.4"></circle><line x1="10.3" y1="10.3" x2="14" y2="14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"></line></svg>
      <input type="text" id="q" placeholder="Search metabolite name or HMDB ID&hellip;" autocomplete="off">
    </div>
    <select id="f-biospecimen"><option value="">All biospecimens</option></select>
    <select id="f-unit"><option value="">All units</option></select>
    <select id="f-age"><option value="">All ages</option></select>
    <select id="f-sex"><option value="">All sexes</option></select>
    <button class="clear-btn" id="clear">Clear filters</button>
  </div>
 
  <div class="results-head">
    <span>Showing <strong id="range-label">&ndash;</strong> of <strong id="total-label">&ndash;</strong> measurements</span>
    <span id="active-filters"></span>
  </div>
 
  <div class="table-card">
    <div class="table-scroll">
      <table class="results">
        <thead>
          <tr>
            <th>Metabolite</th>
            <th>Biospecimen</th>
            <th>Concentration</th>
            <th>Age group</th>
            <th>Sex</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
      <div class="empty-state" id="empty" style="display:none">No measurements match these filters.</div>
    </div>
    <div class="pagination">
      <button id="prev">&larr; Prev</button>
      <span class="pg-info" id="pg-info"></span>
      <button id="next">Next &rarr;</button>
    </div>
  </div>
 
  <footer>
    Generated from <code>hmdb_normal_concentrations_clean.csv</code> via <code>normalize_db.py</code> &middot; metabolite-atlas &middot; <span id="gen-count"></span> measurements loaded in-browser, nothing sent over the network
  </footer>
</main>
 
<script id="atlas-data" type="application/json">__ATLAS_DATA_JSON__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("atlas-data").textContent);
  var metabolites = DATA.metabolites;      // hmdb_id -> name
  var biospecimens = DATA.biospecimens;    // id -> name
  var units = DATA.units;                  // id -> name
  var references = DATA.references;        // id -> [pubmed_id, text]
  var measurements = DATA.measurements;    // [hmdb_id, biospecimen_id, value, unit_id, age, sex, condition, reference_id]
 
  var PAGE_SIZE = 25;
  var page = 0;
  var filtered = measurements;
  var expandedRow = null;
 
  // ---------- stat tiles ----------
  var statsEl = document.getElementById("stats");
  var nRefs = Object.keys(references).length;
  var stats = [
    [measurements.length.toLocaleString(), "measurements"],
    [Object.keys(metabolites).length.toLocaleString(), "metabolites"],
    [Object.keys(biospecimens).length.toLocaleString(), "biospecimens"],
    [nRefs.toLocaleString(), "citations"]
  ];
  statsEl.innerHTML = stats.map(function (s) {
    return '<div class="stat"><div class="n">' + s[0] + '</div><div class="label">' + s[1] + "</div></div>";
  }).join("");
  document.getElementById("gen-count").textContent = measurements.length.toLocaleString();
 
  // ---------- overview chart: measurements per biospecimen ----------
  var bioCounts = {};
  measurements.forEach(function (m) {
    bioCounts[m[1]] = (bioCounts[m[1]] || 0) + 1;
  });
  var bioSorted = Object.keys(bioCounts)
    .map(function (id) { return { id: id, name: biospecimens[id], count: bioCounts[id] }; })
    .sort(function (a, b) { return b.count - a.count; })
    .slice(0, 8);
  var maxCount = bioSorted[0].count;
  document.getElementById("biospecimen-chart").innerHTML = bioSorted.map(function (b) {
    var pct = Math.round((b.count / maxCount) * 100);
    return '<div class="bar-row"><span class="bl">' + escapeHtml(b.name) + '</span>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div>' +
      '<span class="bn">' + b.count.toLocaleString() + "</span></div>";
  }).join("");
 
  // ---------- filter dropdowns ----------
  function fillSelect(id, values) {
    var el = document.getElementById(id);
    values.forEach(function (v) {
      var opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    });
  }
  fillSelect("f-biospecimen", Object.values(biospecimens).sort());
  fillSelect("f-unit", Object.values(units).sort());
  var ageSet = {}, sexSet = {};
  measurements.forEach(function (m) {
    if (m[4]) ageSet[m[4].trim()] = true;
    if (m[5]) sexSet[m[5].trim()] = true;
  });
  fillSelect("f-age", Object.keys(ageSet).sort());
  fillSelect("f-sex", Object.keys(sexSet).sort());
 
  // ---------- filtering ----------
  var qEl = document.getElementById("q");
  var fBio = document.getElementById("f-biospecimen");
  var fUnit = document.getElementById("f-unit");
  var fAge = document.getElementById("f-age");
  var fSex = document.getElementById("f-sex");
 
  function nameToId(map, name) {
    for (var k in map) { if (map[k] === name) return k; }
    return null;
  }
 
  function applyFilters() {
    var q = qEl.value.trim().toLowerCase();
    var bioName = fBio.value;
    var unitName = fUnit.value;
    var age = fAge.value;
    var sex = fSex.value;
 
    filtered = measurements.filter(function (m) {
      if (bioName && biospecimens[m[1]] !== bioName) return false;
      if (unitName && units[m[3]] !== unitName) return false;
      if (age && (!m[4] || m[4].trim() !== age)) return false;
      if (sex && (!m[5] || m[5].trim() !== sex)) return false;
      if (q) {
        var name = (metabolites[m[0]] || "").toLowerCase();
        var hid = m[0].toLowerCase();
        if (name.indexOf(q) === -1 && hid.indexOf(q) === -1) return false;
      }
      return true;
    });
 
    page = 0;
    expandedRow = null;
    renderTable();
    renderActiveFilters();
  }
 
  function renderActiveFilters() {
    var parts = [];
    if (fBio.value) parts.push(fBio.value);
    if (fUnit.value) parts.push(fUnit.value);
    if (fAge.value) parts.push(fAge.value);
    if (fSex.value) parts.push(fSex.value);
    if (qEl.value.trim()) parts.push('"' + qEl.value.trim() + '"');
    document.getElementById("active-filters").textContent = parts.length ? "Filtered by " + parts.join(" &middot; ") : "";
  }
 
  qEl.addEventListener("input", applyFilters);
  [fBio, fUnit, fAge, fSex].forEach(function (el) { el.addEventListener("change", applyFilters); });
  document.getElementById("clear").addEventListener("click", function () {
    qEl.value = ""; fBio.value = ""; fUnit.value = ""; fAge.value = ""; fSex.value = "";
    applyFilters();
  });
 
  // ---------- table rendering ----------
  var tbody = document.getElementById("tbody");
  var emptyEl = document.getElementById("empty");
 
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
 
  function renderTable() {
    var start = page * PAGE_SIZE;
    var pageRows = filtered.slice(start, start + PAGE_SIZE);
 
    if (pageRows.length === 0) {
      tbody.innerHTML = "";
      emptyEl.style.display = "block";
    } else {
      emptyEl.style.display = "none";
      var html = "";
      pageRows.forEach(function (m, i) {
        var idx = start + i;
        var name = metabolites[m[0]] || m[0];
        var bio = biospecimens[m[1]] || "&mdash;";
        var value = m[2];
        var unit = units[m[3]] || "";
        var age = m[4] || '<span class="muted">&mdash;</span>';
        var sex = m[5] || '<span class="muted">&mdash;</span>';
        var refId = m[7];
 
        html += '<tr class="data-row" data-idx="' + idx + '">' +
          '<td><span class="mname">' + escapeHtml(name) + '</span><span class="hid">' + escapeHtml(m[0]) + '</span></td>' +
          '<td><span class="chip">' + escapeHtml(bio) + "</span></td>" +
          '<td class="mono">' + escapeHtml(value) + " " + escapeHtml(unit) + "</td>" +
          "<td>" + age + "</td>" +
          "<td>" + sex + "</td>" +
          "<td>" + (refId != null
            ? '<button class="cite-toggle" data-idx="' + idx + '">cite</button>'
            : '<span class="muted">no source</span>') +
          "</td></tr>";
 
        if (expandedRow === idx) {
          var ref = refId != null ? references[refId] : null;
          html += '<tr class="cite-row"><td colspan="6">';
          if (ref) {
            var pubmedId = ref[0], text = ref[1];
            html += (text ? escapeHtml(text) : "<em>No citation text on file.</em>");
            if (pubmedId) {
              html += ' &mdash; <a href="https://pubmed.ncbi.nlm.nih.gov/' + encodeURIComponent(pubmedId) +
                '/" target="_blank" rel="noopener">PubMed ' + escapeHtml(pubmedId) + "</a>";
            }
          } else {
            html += "<em>No citation on file for this measurement.</em>";
          }
          html += "</td></tr>";
        }
      });
      tbody.innerHTML = html;
    }
 
    var total = filtered.length;
    var rangeStart = total === 0 ? 0 : start + 1;
    var rangeEnd = Math.min(start + PAGE_SIZE, total);
    document.getElementById("range-label").textContent = total === 0 ? "0" : rangeStart.toLocaleString() + "\u2013" + rangeEnd.toLocaleString();
    document.getElementById("total-label").textContent = total.toLocaleString();
 
    var pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
    document.getElementById("pg-info").textContent = "Page " + (page + 1) + " of " + pageCount;
    document.getElementById("prev").disabled = page === 0;
    document.getElementById("next").disabled = page >= pageCount - 1;
  }
 
  tbody.addEventListener("click", function (e) {
    var btn = e.target.closest(".cite-toggle");
    var row = e.target.closest(".data-row");
    if (btn) {
      var idx = parseInt(btn.getAttribute("data-idx"), 10);
      expandedRow = expandedRow === idx ? null : idx;
      renderTable();
    } else if (row && !e.target.closest("a")) {
      var idx2 = parseInt(row.getAttribute("data-idx"), 10);
      var m = measurements[idx2];
      if (m[7] != null) {
        expandedRow = expandedRow === idx2 ? null : idx2;
        renderTable();
      }
    }
  });
 
  document.getElementById("prev").addEventListener("click", function () {
    if (page > 0) { page--; renderTable(); }
  });
  document.getElementById("next").addEventListener("click", function () {
    var pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (page < pageCount - 1) { page++; renderTable(); }
  });
 
  renderTable();
})();
</script>
"""
 
 
def export_data(conn):
    """Reads the five normalized tables and returns a compact dict ready to
    embed as JSON: dimension tables keyed by id/hmdb_id, measurements as
    plain arrays (matching column order the page's JS expects)."""
    conn.row_factory = sqlite3.Row
 
    metabolites = {
        r["hmdb_id"]: r["metabolite_name"]
        for r in conn.execute("SELECT hmdb_id, metabolite_name FROM metabolites")
    }
    biospecimens = {
        r["biospecimen_id"]: r["name"]
        for r in conn.execute("SELECT biospecimen_id, name FROM biospecimens")
    }
    units = {
        r["unit_id"]: r["unit_name"]
        for r in conn.execute("SELECT unit_id, unit_name FROM concentration_units")
    }
    references = {
        r["reference_id"]: [r["pubmed_id"], r["reference_text"]]
        for r in conn.execute('SELECT reference_id, pubmed_id, reference_text FROM "references"')
    }
 
    measurements = []
    for r in conn.execute(
        """SELECT hmdb_id, biospecimen_id, concentration_value_raw, unit_id,
                  subject_age, subject_sex, subject_condition, reference_id
           FROM measurements"""
    ):
        measurements.append([
            r["hmdb_id"], r["biospecimen_id"], r["concentration_value_raw"], r["unit_id"],
            r["subject_age"], r["subject_sex"], r["subject_condition"], r["reference_id"],
        ])
 
    return {
        "metabolites": metabolites,
        "biospecimens": biospecimens,
        "units": units,
        "references": references,
        "measurements": measurements,
    }
 
 
def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Couldn't find {DB_PATH}. Run normalize_db.py first to build it "
            f"from the CSV, then run this script from the same folder."
        )
 
    print(f"Reading {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH)
    data = export_data(conn)
    conn.close()
    print(f"  {len(data['measurements']):,} measurements, "
          f"{len(data['metabolites']):,} metabolites, "
          f"{len(data['biospecimens']):,} biospecimens, "
          f"{len(data['references']):,} references")
 
    data_json = json.dumps(data, separators=(",", ":"))
    # Guard against a stray "</script" inside any string value breaking the
    # embedding <script type="application/json"> tag.
    data_json_safe = data_json.replace("</script", "<\\/script")
 
    page = HTML_TEMPLATE.replace("__ATLAS_DATA_JSON__", data_json_safe)
 
    OUT_PATH.write_text(page, encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"Wrote {OUT_PATH} ({size_mb:.1f} MB)")
    print("Open it directly in a browser, or host it as a static file -- "
          "everything needed is in that one file.")
 
 
if __name__ == "__main__":
    main()
 

