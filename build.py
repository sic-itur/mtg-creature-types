import json
from collections import defaultdict
from pathlib import Path

import requests
import ijson

OUT_DIR = Path("site")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCRY_BULK = "https://api.scryfall.com/bulk-data"
MANA_ORDER = ["W", "U", "B", "R", "G", "C"]
EXTRA_LAYOUTS = { "token", "double_faced_token", "emblem", "vanguard", "scheme", "plane", "phenomenon", }

def get_oracle_cards_download_uri() -> str:
    r = requests.get(SCRY_BULK, timeout=60)
    r.raise_for_status()
    items = r.json()["data"]
    for it in items:
        if it.get("type") == "oracle_cards" or it.get("name") == "Oracle Cards":
            return it["download_uri"]
    raise RuntimeError("Could not find Oracle Cards bulk data item.")

def get_creature_type_allowlist() -> set[str]:
    r = requests.get("https://api.scryfall.com/catalog/creature-types", timeout=60)
    r.raise_for_status()
    return {x.lower() for x in r.json().get("data", [])}

def is_creature_type_line(type_line: str) -> bool:
    return "Creature" in (type_line or "")

def extract_subtypes_from_type_line(type_line: str, allowed: set[str]) -> list[str]:
    if "—" not in type_line:
        return []
    right = type_line.split("—", 1)[1].strip()
    tokens = [t.strip(" ,.;:()[]{}\"'") for t in right.split() if t.strip()]
    # keeps only real creature types
    return [t for t in tokens if t.lower() in allowed]

def iter_creature_faces(card: dict) -> list[dict]:
    """
    returns a list of creature faces.
    if the card has card_faces, each face is examined independently.
    otherwise, treat the card as a single face.
    """
    faces = card.get("card_faces")
    if isinstance(faces, list) and faces:
        return [f for f in faces if is_creature_type_line(f.get("type_line", ""))]
    # single-face card
    return [card] if is_creature_type_line(card.get("type_line", "")) else []

def main():
    uri = get_oracle_cards_download_uri()
    resp = requests.get(uri, stream=True, timeout=180)
    resp.raise_for_status()
    resp.raw.decode_content = True

    total = defaultdict(int)
    colour_counts = defaultdict(lambda: defaultdict(int))
    legendary = defaultdict(int)

    cards_iter = ijson.items(resp.raw, "item")

    allowed_types = get_creature_type_allowlist()

    for card in cards_iter:
        games = card.get("games") or []
        if "paper" not in games:
            continue
      
        if card.get("layout") in EXTRA_LAYOUTS:
            continue
        # excludes cards from "memorabilia" sets
        if card.get("set_type") == "memorabilia":
            continue
        # excludes un-/funny cards
        if card.get("set_type") == "funny" or card.get("funny") is True:
            continue
        
        # determines if this card has any creature face at all
        creature_faces = iter_creature_faces(card)
        if not creature_faces:
            continue

        # uses overall card color_identity (shared across faces)
        ci = card.get("color_identity") or []
        ci_set = set(ci) if ci else {"C"}

        for face in creature_faces:
            type_line = face.get("type_line") or ""
            subtypes = extract_subtypes_from_type_line(type_line, allowed_types)
            if not subtypes:
                continue

            is_legend = "Legendary" in type_line

            for st in subtypes:
                total[st] += 1

                for c in ci_set:
                    if c in ["W", "U", "B", "R", "G"]:
                        colour_counts[st][c] += 1
                    else:
                        colour_counts[st]["C"] += 1

                if is_legend:
                    legendary[st] += 1

    rows = []
    for st, n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0].lower())):
        counts = {c: int(colour_counts[st].get(c, 0)) for c in MANA_ORDER}
        perc = {c: (counts[c] / n) if n else 0.0 for c in MANA_ORDER}

        rows.append({
            "type": st,
            "count": int(n),
            "legendary": int(legendary.get(st, 0)),
            "colourCounts": counts,
            "colourPerc": perc,
        })

    data = {
        "rows": rows
    }

    (OUT_DIR / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    build_html()
    print("Built site/data.json and site/index.html")

def build_html():
    html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>MTG Creature Types Index</title>
  <style>
    :root {
      --bg: #111318;
      --panel: #171a22;
      --panel2: #1c202b;
      --border: #2a2f3b;
      --text: #f2f2f2;
      --muted: #aab1bf;
      --link: #9ccfff;
      --pill: #141822;
      --shadow: rgba(0,0,0,0.35);
      --radius: 0.75rem;
    }
    body {
      margin: 1.125rem;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }
    html::-webkit-scrollbar {
    width: 14px;
    }
    html::-webkit-scrollbar-track {
        background: transparent;
    }
    html::-webkit-scrollbar-thumb {
        background: #394154;
        border-radius: 999px;
        border: 3px solid transparent;
        background-clip: content-box;
    }
    h1 { font-size: 1.35rem; margin: 0 0 0.375rem; }
    .sub { font-size: 0.9rem; color: var(--muted); margin: 0 0 1rem; line-height: 1.4; }
    .bar {
      display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap;
      margin: 1.125rem 0 0.75rem;
    }
    input {
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 0.625rem 0.75rem;
      border-radius: var(--radius);
      min-width: 320px;
      outline: none;
    }
    input::placeholder { color: rgba(232,238,246,0.45); }
    .card {
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      box-shadow: 0 0.875rem 2.5rem var(--shadow);
      margin: 1.5rem 0;
    }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      background: var(--panel);
      backdrop-filter: blur(0.5rem);
      text-align: left;
      font-size: 0.8rem;
      color: var(--muted);
      border-bottom: 1px solid var(--border);
      padding: 0.625rem;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
      vertical-align: top;
    }
    tbody td {
      background: color-mix(in srgb, var(--panel2) 40%, transparent);
      border-bottom: 1px solid var(--border);
      padding: 0.625rem 0.625rem;
      vertical-align: middle;
      font-size: 0.875rem;
    }
    tbody tr:hover { background: var(--panel2); }
    tbody tr:last-child td { border-bottom: 0; }
    .num { font-variant-numeric: tabular-nums; }
    a { color: var(--link); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .type a { font-weight: 650; }
    .lucide { width: 1rem; }
    th.mana .manaLabel { display: inline-flex; align-items: center; gap: 0.4rem; white-space: nowrap; }
    th.mana .manaHeadIcon { width: 1rem; height: 1rem; display: block; flex: 0 0 auto; }
    thead th.noSort { cursor: default; }
    .colourIcons { display: flex; gap: 0.375rem; align-items: center; }
    .colourIcons img { width: 1rem; height: 1rem; display: block; }
    .cellNum { font-variant-numeric: tabular-nums; }
    .cellPct { color: var(--muted); font-size: 0.75rem; margin-left: 0.125rem; }
    .cellMuted { color: rgba(232,238,246,0.35); }
    .sortHint { color: rgba(232,238,246,0.35); font-size: 0.625rem; margin-left: 0.375rem; }
    .footer { color: var(--muted); font-size: 0.75rem; line-height: 1.45; }
  </style>
</head>
<body>
<h1>MTG Creature Types Index</h1>
<p class="sub">
  Auto-updated daily from Scryfall bulk data. Inspired by Smileylich’s <a href="https://www.smileylich.com/mtg/magocracy/Magocracy_C1.html">Creature Type List</a>.
</p>

<div class="bar">
  <input id="filter" placeholder="Filter creature types… (e.g. Human, Elf, Zombie)" />
</div>

<div class="card">
  <table>
    <thead>
      <tr>
        <th data-key="type">Creature Type <span class="sortHint" id="sh_type"></span></th>
        <th data-key="count" class="num">Count <span class="sortHint" id="sh_count"></span></th>
        <th data-key="colours">Colours <span class="sortHint" id="sh_colours"></span></th>
        <th data-key="W" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/W.svg" alt="W" title="White">White</span></th>
        <th data-key="U" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/U.svg" alt="U" title="Blue">Blue</span></th>
        <th data-key="B" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/B.svg" alt="B" title="Black">Black</span></th>
        <th data-key="R" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/R.svg" alt="R" title="Red">Red</span></th>
        <th data-key="G" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/G.svg" alt="G" title="Green">Green</span></th>
        <th data-key="C" class="mana"><span class="manaLabel"><img class="manaHeadIcon" src="./assets/mana/C.svg" alt="C" title="Colourless">Colourless</span></th>
        <th data-key="legendary" class="num">Legendaries<span class="sortHint" id="sh_legendary"></span></th>
        <th class="noSort">Support Cards</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<div class="footer" id="footer"></div>

<script>
const MANA = ["W","U","B","R","G","C"];

function scryNoncreatureSupport(t) {
  const q = encodeURIComponent(`o:${t} -t:${t}`);
  return `https://scryfall.com/search?as=grid&order=name&q=${q}`;
}

function scryCreatureType(t) {
  const q = encodeURIComponent(`t:creature t:${t}`);
  return `https://scryfall.com/search?as=grid&order=name&q=${q}`;
}

function pctStr(p) {
  return (p * 100).toFixed(1) + "%";
}

function colourIconsHTML(row) {
  const icons = [];
  for (const c of MANA) {
    const cnt = row.colourCounts[c] || 0;
    if (cnt > 0) {
      icons.push(`<img src="./assets/mana/${c}.svg" alt="${c}" title="${c}" />`);
    }
  }
  return `<div class="colourIcons">${icons.join("") || "—"}</div>`;
}

function colourCellHTML(row, c) {
  const cnt = row.colourCounts[c] || 0;
  const p = row.colourPerc[c] || 0;
  if (!cnt) return `<span class="cellMuted">—</span>`;
  return `<span class="cellNum">${cnt}</span> <span class="cellPct">${pctStr(p)}</span>`;
}

function render(rows) {
  const tbody = document.getElementById("tbody");
  tbody.innerHTML = "";

  const COLS = 11; // type, count, colours, W, U, B, R, G, C, legendaries, support

  if (!rows || rows.length === 0) {
    const q = (document.getElementById("filter")?.value || "").trim();
    const msg = q ? `No matches for “${q}”.` : "No data.";
    renderEmptyRow(tbody, COLS, msg);
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="type"><a href="${scryCreatureType(row.type)}" target="_blank" rel="noreferrer">${row.type}</a></td>
      <td class="num">${row.count}</td>
      <td>${colourIconsHTML(row)}</td>

      <td class="num">${colourCellHTML(row, "W")}</td>
      <td class="num">${colourCellHTML(row, "U")}</td>
      <td class="num">${colourCellHTML(row, "B")}</td>
      <td class="num">${colourCellHTML(row, "R")}</td>
      <td class="num">${colourCellHTML(row, "G")}</td>
      <td class="num">${colourCellHTML(row, "C")}</td>

      <td class="num">${row.legendary}</td>
      <td><a href="${scryNoncreatureSupport(row.type)}" target="_blank" rel="noreferrer"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-square-arrow-out-up-right-icon lucide-square-arrow-out-up-right"><path d="M21 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6"/><path d="m21 3-9 9"/><path d="M15 3h6v6"/></svg></a></td>
    `;
    tbody.appendChild(tr);
  }
}

function setSortHints(activeKey, dir) {
  for (const el of document.querySelectorAll(".sortHint")) el.textContent = "";
  const hint = dir === "asc" ? "▲" : "▼";
  const id = "sh_" + activeKey;
  const el = document.getElementById(id);
  if (el) el.textContent = hint;
}

function sortRows(rows, key, dir) {
  const mult = dir === "asc" ? 1 : -1;

  return [...rows].sort((a, b) => {
    if (key === "type") return a.type.localeCompare(b.type) * mult;

    if (key === "colours") {
      // Sort by how many different colours show up (including C)
      const da = MANA.reduce((s,c)=> s + ((a.colourCounts[c]||0) > 0 ? 1 : 0), 0);
      const db = MANA.reduce((s,c)=> s + ((b.colourCounts[c]||0) > 0 ? 1 : 0), 0);
      return (da - db) * mult;
    }

    if (MANA.includes(key)) {
      // Sort by the per-colour count
      return ((a.colourCounts[key] || 0) - (b.colourCounts[key] || 0)) * mult;
    }

    if (key === "support") return a.type.localeCompare(b.type) * mult;

    return ((a[key] || 0) - (b[key] || 0)) * mult;
  });
}

function renderEmptyRow(tbody, colCount, message) {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td class="cellMuted" colspan="${colCount}">${message}</td>`;
  tbody.appendChild(tr);
}

async function main() {
  const res = await fetch("./data.json");
  const data = await res.json();
  const allRows = data.rows;

  const filterEl = document.getElementById("filter");
  let sortKey = "count";
  let sortDir = "desc";

  function currentRows() {
    const f = (filterEl.value || "").trim().toLowerCase();
    const filtered = f
      ? allRows.filter(r => r.type.toLowerCase().includes(f))
      : allRows;

    const sorted = sortRows(filtered, sortKey, sortDir);
    setSortHints(sortKey, sortDir);
    return sorted;
  }

  function rerender() { render(currentRows()); }

  filterEl.addEventListener("input", rerender);

  document.querySelectorAll("thead th").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-key");
      if (!key) return;
      if (sortKey === key) sortDir = (sortDir === "asc") ? "desc" : "asc";
      else {
        sortKey = key;
        sortDir = (key === "type") ? "asc" : "desc";
      }
      rerender();
    });
  });

  document.getElementById("footer").innerHTML = `
    <div><b>Notes:</b></div>
    <div>• Counts/colours/legendaries are computed from <b>creature faces only</b> (<code>t:creature</code>) and use colour identity for the colour breakdown.</div>
    <div>• Creature types are limited to Scryfall’s official <a href="https://scryfall.com/docs/api/catalogs/creature-types">creature-types</a> catalog based on current Oracle data.</div>
    <div>• The “Support Cards” column uses <code>o:TYPE -t:creature</code> to find relevant instants/enchantments/etc.</div>
  `;

  rerender();
}
main();
</script>
</body>
</html>
"""
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")

if __name__ == "__main__":
    main()