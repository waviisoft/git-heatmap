#!/usr/bin/env python3
"""
git-heatmap.py — GitHub-style commit heat map for any git repo.

Usage:
  python3 git-heatmap.py                  # run from inside a git repo
  python3 git-heatmap.py /path/to/repo    # explicit repo path
  python3 git-heatmap.py --no-open        # generate file but don't open browser
  python3 git-heatmap.py --out heat.html  # custom output path
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta

# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Generate a commit heat map for a git repo.")
parser.add_argument("repo", nargs="?", default=".", help="Path to git repo (default: current directory)")
parser.add_argument("--out", default="", help="Output HTML path (default: temp file)")
parser.add_argument("--no-open", action="store_true", help="Don't open browser after generating")
parser.add_argument(
    "--config",
    default="",
    help="Path to JSON config file (default: .git-heatmap.json in repo root)"
)
parser.add_argument(
    "--merge",
    action="append",
    default=[],
    metavar="PRIMARY:ALT1,ALT2",
    help="Merge author names into one; repeatable. e.g. --merge 'John Doe:jdoe,j.doe'"
)
args = parser.parse_args()

repo_path = os.path.abspath(args.repo)
if not os.path.isdir(os.path.join(repo_path, ".git")):
    # Walk up to find .git
    cur = repo_path
    while cur != os.path.dirname(cur):
        if os.path.isdir(os.path.join(cur, ".git")):
            repo_path = cur
            break
        cur = os.path.dirname(cur)
    else:
        print(f"Error: no git repository found at or above {args.repo}", file=sys.stderr)
        sys.exit(1)


def git(*cmd):
    return subprocess.check_output(["git", "-C", repo_path, *cmd], text=True).strip()


# ── Repo metadata ─────────────────────────────────────────────────────────────

try:
    remote_url = git("remote", "get-url", "origin")
except subprocess.CalledProcessError:
    remote_url = ""

# Parse GitHub org/repo from SSH or HTTPS remote URL
gh_org, gh_repo_name = "", ""
m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", remote_url)
if m:
    gh_org, gh_repo_name = m.group(1), m.group(2)

gh_base = f"https://github.com/{gh_org}/{gh_repo_name}" if gh_org else ""

repo_display = gh_repo_name or os.path.basename(repo_path)

# ── Git log ───────────────────────────────────────────────────────────────────

def _find_config(explicit_path, repo_root):
    if explicit_path:
        return explicit_path
    candidate = os.path.join(repo_root, ".git-heatmap.json")
    return candidate if os.path.isfile(candidate) else None

def _load_config(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(1)

def _aliases_from_config(cfg):
    alias = {}
    for primary, alts in cfg.get("merge_authors", {}).items():
        if not isinstance(alts, list):
            print(f"Warning: merge_authors[{primary!r}] must be a list, skipping", file=sys.stderr)
            continue
        for alt in alts:
            if not isinstance(alt, str) or alt == primary:
                continue
            if alt in alias and alias[alt] != primary:
                print(f"Warning: alias {alt!r} already mapped; keeping first mapping", file=sys.stderr)
                continue
            alias[alt] = primary
    return alias

def _aliases_from_cli(merge_args):
    alias = {}
    for token in merge_args:
        if ":" not in token:
            print(f"Warning: --merge {token!r} has no colon separator, skipping", file=sys.stderr)
            continue
        primary, _, rest = token.partition(":")
        primary = primary.strip()
        if not primary:
            continue
        for alt in (a.strip() for a in rest.split(",") if a.strip()):
            if alt == primary:
                continue
            if alt in alias and alias[alt] != primary:
                print(f"Warning: alias {alt!r} already mapped via CLI; keeping first", file=sys.stderr)
                continue
            alias[alt] = primary
    return alias

def _resolve_chains(alias):
    resolved = {}
    for src, dst in alias.items():
        seen = {src}
        while dst in alias and alias[dst] not in seen:
            seen.add(dst)
            dst = alias[dst]
        resolved[src] = dst
    return resolved

def _build_alias(explicit_config, merge_args, repo_root):
    alias = {}
    cfg_path = _find_config(explicit_config, repo_root)
    if cfg_path:
        alias.update(_aliases_from_config(_load_config(cfg_path)))
    alias.update(_aliases_from_cli(merge_args))
    return _resolve_chains(alias)

ALIAS = _build_alias(args.config, args.merge, repo_path)

raw_log = git("log", "--format=%H\t%ad\t%an\t%s", "--date=iso-strict")
commit_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
commit_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

for line in raw_log.splitlines():
    parts = line.split("\t", 3)
    if len(parts) != 4:
        continue
    full_hash, dt_iso, author, subject = parts
    author = ALIAS.get(author, author)
    try:
        dt = datetime.fromisoformat(dt_iso)
    except ValueError:
        continue
    date_str = dt.date().isoformat()
    commit_index[(author, date_str)].append({
        "hash": full_hash,
        "short": full_hash[:7],
        "dt": dt_iso,
        "subject": subject,
    })
    commit_counts[author][date_str] += 1

# ── Authors ───────────────────────────────────────────────────────────────────

# Rank by total commits; assign colour palette (up to 8 authors)
PALETTES = [
    ["#1c2128", "#9be9a8", "#40c463", "#30a14e", "#216e39"],   # green
    ["#1c2128", "#b8c9f8", "#7094ef", "#3a66d4", "#1a3fa0"],   # blue
    ["#1c2128", "#ffd6a5", "#fdbc6e", "#e8851b", "#b85e00"],   # orange
    ["#1c2128", "#f8b4c8", "#e8648c", "#c62060", "#8b0038"],   # red/pink
    ["#1c2128", "#d2b8f8", "#a370ef", "#7c35d4", "#4f0fa0"],   # purple
    ["#1c2128", "#b8f0f8", "#50d4e8", "#10a8c0", "#006880"],   # teal
    ["#1c2128", "#f8e8a8", "#e8c840", "#c0a000", "#806800"],   # yellow
    ["#1c2128", "#c8f8c8", "#70d870", "#30a830", "#107010"],   # lime
]
AVATAR_COLORS = ["#2da44e", "#1a3fa0", "#b85e00", "#c62060",
                 "#7c35d4", "#006880", "#c0a000", "#107010"]
ACCENT_COLORS = ["#40c463", "#3a66d4", "#e8851b", "#e8648c",
                 "#a370ef", "#50d4e8", "#e8c840", "#70d870"]

all_authors_ranked = sorted(
    commit_counts.keys(),
    key=lambda a: -sum(commit_counts[a].values())
)

# Assign palette by rank
authors = all_authors_ranked
def initials(name):
    parts = name.split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else name[:2].upper()

AUTHOR_META = {}
for i, a in enumerate(authors):
    pi = i % len(PALETTES)
    AUTHOR_META[a] = {
        "initials": initials(a),
        "palette": PALETTES[pi],
        "avatar_bg": AVATAR_COLORS[pi],
        "accent": ACCENT_COLORS[pi],
    }

# ── Calendar helpers ──────────────────────────────────────────────────────────

def first_sunday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday() + 1) if d.weekday() != 6 else d


all_dates = sorted({ds for a in commit_counts.values() for ds in a})
if not all_dates:
    print("No commits found.", file=sys.stderr)
    sys.exit(0)

first_commit_date = date.fromisoformat(all_dates[0])
last_commit_date  = date.fromisoformat(all_dates[-1])
global_start = first_sunday_on_or_before(first_commit_date)
global_end   = last_commit_date + timedelta(days=14)

all_weeks: list[list[date]] = []
cur = global_start
while cur <= global_end:
    all_weeks.append([cur + timedelta(days=i) for i in range(7)])
    cur += timedelta(weeks=1)

# ── Heatmap rendering ─────────────────────────────────────────────────────────

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_DISPLAY  = ["", "M", "", "W", "", "F", ""]   # only Mon/Wed/Fri labelled

def commit_level(count: int) -> int:
    if count == 0: return 0
    if count == 1: return 1
    if count <= 3: return 2
    if count <= 5: return 3
    return 4


def compute_rendered_weeks() -> list:
    """Active weeks plus buffers so each year >= 3 weeks and each month >= 2 weeks."""
    active = {
        i for i, week in enumerate(all_weeks)
        if any(commit_counts[a].get(d.isoformat(), 0) > 0 for a in authors for d in week)
    }
    included = set(active)

    # Year pass: ensure >= 3 weeks per year
    for year in {all_weeks[i][0].year for i in included}:
        idxs = [i for i, w in enumerate(all_weeks) if w[0].year == year]
        in_y = {i for i in idxs if i in included}
        while len(in_y) < min(3, len(idxs)):
            cands = [i for i in idxs if i not in in_y]
            best = min(cands, key=lambda c: min(abs(c - j) for j in in_y))
            included.add(best)
            in_y.add(best)

    # Month pass: only months that have at least 1 commit (not pure year-buffers)
    for ym in {(all_weeks[i][0].year, all_weeks[i][0].month) for i in active}:
        idxs = [i for i, w in enumerate(all_weeks) if (w[0].year, w[0].month) == ym]
        in_m = {i for i in idxs if i in included}
        while len(in_m) < min(2, len(idxs)):
            cands = [i for i in idxs if i not in in_m]
            best = min(cands, key=lambda c: min(abs(c - j) for j in in_m))
            included.add(best)
            in_m.add(best)

    return [all_weeks[i] for i in sorted(included, reverse=True)]


def render_scroll_view() -> str:
    """Return the unified horizontally-scrolling heatmap HTML (newest week left)."""
    rev_weeks = compute_rendered_weeks()
    nw = len(rev_weeks)
    parts = []

    parts.append('<div id="heatmap-wrapper">')
    parts.append('<table id="heatmap-table">')

    # Compute colspan spans for the two header rows
    year_spans  = []  # [(year, colspan), ...]
    month_spans = []  # [((year, month), colspan), ...]
    cy = cm = None
    cy_cnt = cm_cnt = 0
    for week in rev_weeks:
        fd = week[0]
        y, ym = fd.year, (fd.year, fd.month)
        if y != cy:
            if cy is not None:
                year_spans.append((cy, cy_cnt))
            cy, cy_cnt = y, 1
        else:
            cy_cnt += 1
        if ym != cm:
            if cm is not None:
                month_spans.append((cm, cm_cnt))
            cm, cm_cnt = ym, 1
        else:
            cm_cnt += 1
    if cy is not None:
        year_spans.append((cy, cy_cnt))
    if cm is not None:
        month_spans.append((cm, cm_cnt))

    # Year row (sticky top:0, sticky left:156px)
    parts.append('<thead>')
    parts.append('<tr class="year-row">')
    parts.append('<th class="corner-cell" rowspan="2" colspan="2"></th>')
    for i, (year, span) in enumerate(year_spans):
        sep = ' year-sep' if i > 0 else ''
        parts.append(f'<th class="year-header{sep}" colspan="{span}">{year}</th>')
    parts.append('</tr>')
    # Month row (sticky top:20px)
    parts.append('<tr class="month-row">')
    prev_my = None
    for (year, month), span in month_spans:
        sep = ' year-sep' if (prev_my is not None and year != prev_my) else ''
        prev_my = year
        parts.append(f'<th class="month-header{sep}" colspan="{span}">{MONTH_NAMES[month]}</th>')
    parts.append('</tr>')
    parts.append('</thead>')

    # Precompute which week indices mark a year boundary (for the separator line)
    year_sep_indices = {
        wi for wi in range(1, len(rev_weeks))
        if rev_weeks[wi][0].year != rev_weeks[wi - 1][0].year
    }

    # Author rows: 7 rows per author (Sun–Sat)
    parts.append('<tbody>')
    for ai, author in enumerate(authors):
        meta = AUTHOR_META[author]
        ini  = meta["initials"]
        ac   = meta["accent"]
        for di in range(7):
            parts.append('<tr class="day-row">')
            if di == 0:
                parts.append(
                    f'<th class="author-cell" rowspan="7">'
                    f'<div class="grid-avatar" style="background:{meta["avatar_bg"]}">{ini}</div>'
                    f'</th>'
                )
            parts.append(f'<th class="day-cell">{DAY_DISPLAY[di]}</th>')
            for wi, week in enumerate(rev_weeks):
                d          = week[di]
                cnt        = commit_counts[author].get(d.isoformat(), 0)
                fill       = meta["palette"][commit_level(cnt)]
                date_iso   = d.isoformat()
                date_label = d.strftime("%b %-d, %Y")
                tip        = f"{cnt} commit{'s' if cnt != 1 else ''} on {date_label}"
                sep        = ' year-sep' if wi in year_sep_indices else ''
                if cnt > 0:
                    parts.append(
                        f'<td class="cell{sep}" data-author="{author}" data-date="{date_iso}"'
                        f' data-count="{cnt}" data-label="{date_label}"'
                        f' title="{tip}" style="cursor:pointer;">'
                        f'<div class="dot" style="background:{fill};"></div></td>'
                    )
                else:
                    parts.append(
                        f'<td class="cell{sep}" title="{tip}">'
                        f'<div class="dot" style="background:{fill};"></div></td>'
                    )
            parts.append('</tr>')
        if ai < len(authors) - 1:
            parts.append(f'<tr class="author-sep"><td colspan="{nw + 2}"></td></tr>')
    parts.append('</tbody></table></div>')
    return "\n".join(parts)

# ── Build scroll view ─────────────────────────────────────────────────────────

scroll_view = render_scroll_view()

# ── Legend ────────────────────────────────────────────────────────────────────

legend_items = []
for a in authors:
    meta = AUTHOR_META[a]
    swatches = "".join(
        f'<span style="display:inline-block;width:10px;height:10px;background:{c};border-radius:2px;"></span>'
        for c in meta["palette"][1:]
    )
    total = sum(commit_counts[a].values())
    legend_items.append(
        f'<div class="legend-author">'
        f'<div class="legend-avatar" style="background:{meta["avatar_bg"]}">{meta["initials"]}</div>'
        f'<div><div style="font-size:13px;font-weight:600;color:#e6edf3;">{a}</div>'
        f'<div style="display:flex;align-items:center;gap:3px;margin-top:4px;">'
        f'<span style="font-size:11px;color:#8b949e;margin-right:2px;">Less</span>{swatches}'
        f'<span style="font-size:11px;color:#8b949e;margin-left:2px;">More</span></div></div>'
        f'<div style="font-size:12px;color:#8b949e;margin-left:auto;">{total} total</div></div>'
    )

total_all = sum(sum(commit_counts[a].values()) for a in authors)
gh_link = (f' · <a href="{gh_base}" style="color:#58a6ff;text-decoration:none;" '
           f'target="_blank" rel="noopener">{gh_org}/{gh_repo_name}</a>') if gh_base else ""

# ── JavaScript (inline, no f-string conflicts) ────────────────────────────────

commit_data_json = json.dumps(
    {f"{a}||{d}": v for (a, d), v in commit_index.items()},
    ensure_ascii=False
)

js = r"""
const COMMIT_DATA = __COMMIT_DATA__;
const GH_BASE     = "__GH_BASE__";

function linkifySubject(text) {
  const esc = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  // cross-repo  org/repo#number
  const pass1 = esc.replace(
    /([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)#(\d+)/g,
    (_, org, repo, num) =>
      `<a href="https://github.com/${org}/${repo}/issues/${num}" target="_blank" rel="noopener">${org}/${repo}#${num}</a>`
  );
  // same-repo  #number  (not preceded by slash or word chars)
  return pass1.replace(
    /(?<![A-Za-z0-9_.\/-])#(\d+)/g,
    (_, num) => `<a href="${GH_BASE}/issues/${num}" target="_blank" rel="noopener">#${num}</a>`
  );
}

function formatDatetime(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month:'short', day:'numeric', year:'numeric',
      hour:'numeric', minute:'2-digit', timeZoneName:'short'
    });
  } catch(e) { return iso; }
}

const overlay  = document.getElementById('overlay');
const titleEl  = document.getElementById('overlay-title');
const listEl   = document.getElementById('overlay-list');
const closeBtn = document.getElementById('overlay-close');

function showOverlay(author, dateStr, dateLabel, rect) {
  const key     = author + '||' + dateStr;
  const entries = COMMIT_DATA[key] || [];
  if (!entries.length) return;

  titleEl.textContent = dateLabel + ' · ' + author;
  listEl.innerHTML = entries.map(c => `
    <li class="commit-item">
      <div class="commit-meta">
        <a class="commit-hash" href="${GH_BASE}/commit/${c.hash}" target="_blank" rel="noopener">${c.short}</a>
        <span class="commit-time">${formatDatetime(c.dt)}</span>
      </div>
      <div class="commit-subject">${linkifySubject(c.subject)}</div>
    </li>`).join('');

  overlay.classList.add('visible');
  // getBoundingClientRect() is viewport-relative; overlay is position:fixed so coords match directly.
  const vw = window.innerWidth, vh = window.innerHeight;
  const ow = overlay.offsetWidth,  oh = overlay.offsetHeight;
  let left = rect.right + 8, top = rect.top;
  if (left + ow > vw - 8)  left = rect.left - ow - 8;
  if (left < 8)             left = 8;
  if (top + oh > vh - 8)   top  = vh - oh - 8;
  if (top < 8)              top  = 8;
  overlay.style.left = left + 'px';
  overlay.style.top  = top  + 'px';
}

function hideOverlay() { overlay.classList.remove('visible'); }

document.addEventListener('click', e => {
  const cell = e.target.closest('td.cell');
  if (cell) {
    if (parseInt(cell.dataset.count || '0', 10) === 0) return;
    e.stopPropagation();
    showOverlay(cell.dataset.author, cell.dataset.date, cell.dataset.label, cell.getBoundingClientRect());
    return;
  }
  if (e.target === closeBtn || closeBtn.contains(e.target)) { hideOverlay(); return; }
  if (overlay.classList.contains('visible') && !overlay.contains(e.target)) hideOverlay();
});

document.addEventListener('keydown', e => { if (e.key === 'Escape') hideOverlay(); });

"""

js = js.replace("__COMMIT_DATA__", commit_data_json).replace("__GH_BASE__", gh_base)

# ── Assemble HTML ─────────────────────────────────────────────────────────────

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{repo_display} — Commit Heat Map</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
     background:#0d1117;color:#c9d1d9;padding:32px 24px;min-height:100vh}}
h1{{font-size:20px;font-weight:600;color:#e6edf3;margin-bottom:4px}}
.subtitle{{font-size:13px;color:#8b949e;margin-bottom:24px}}
.legend-strip{{display:flex;flex-direction:column;gap:10px;background:#161b22;
              border:1px solid #30363d;border-radius:8px;padding:16px 20px;margin-bottom:28px}}
.legend-author{{display:flex;align-items:center;gap:12px}}
.legend-avatar{{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;
               justify-content:center;font-weight:700;font-size:11px;color:#fff;flex-shrink:0}}
#heatmap-wrapper{{overflow:auto;max-height:80vh;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:8px 12px 8px 0;margin-bottom:20px}}
#heatmap-table{{border-collapse:separate;border-spacing:0}}
th.corner-cell{{position:sticky;top:0;left:0;z-index:5;background:#161b22;min-width:52px}}
th.year-header{{position:sticky;top:0;left:52px;z-index:3;background:#161b22;height:20px;font-size:11px;font-weight:700;color:#e6edf3;text-align:left;white-space:nowrap;padding:0 0 3px 4px;vertical-align:bottom}}
th.year-header.year-sep{{box-sizing:content-box;border-left:10px solid #161b22;padding-left:4px}}
th.month-header{{position:sticky;top:20px;left:52px;z-index:3;background:#161b22;height:16px;font-size:9px;font-weight:400;color:#8b949e;text-align:left;white-space:nowrap;padding:0 0 2px 4px;vertical-align:bottom}}
th.month-header.year-sep{{box-sizing:content-box;border-left:10px solid #161b22}}
td.cell.year-sep{{box-sizing:content-box;border-left:10px solid #161b22}}
th.author-cell{{position:sticky;left:0;z-index:1;background:#161b22;width:36px;min-width:36px;max-width:36px;padding:4px 4px;text-align:center;vertical-align:middle}}
.grid-avatar{{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;color:#fff;margin:0 auto}}
th.day-cell{{position:sticky;left:36px;z-index:1;background:#161b22;width:16px;min-width:16px;font-size:9px;font-weight:400;color:#656d76;text-align:right;padding:0 3px 0 0}}
td.cell{{width:12px;height:12px;padding:1px;border:none;vertical-align:top}}
div.dot{{width:10px;height:10px;border-radius:2px}}
tr.author-sep td{{height:10px;padding:0}}
tr.day-row{{height:12px}}
#overlay{{position:fixed;z-index:1000;background:#1c2128;border:1px solid #30363d;
         border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.5);
         min-width:280px;max-width:440px;
         max-height:calc(100vh - 16px);
         display:none;flex-direction:column}}
#overlay.visible{{display:flex}}
#overlay-header{{display:flex;justify-content:space-between;align-items:flex-start;
                gap:8px;flex-shrink:0;
                padding:14px 16px 10px;border-bottom:1px solid #30363d}}
#overlay-title{{font-size:13px;font-weight:600;color:#e6edf3;line-height:1.3}}
#overlay-close{{background:none;border:none;color:#8b949e;cursor:pointer;
               font-size:16px;line-height:1;padding:0 2px;flex-shrink:0}}
#overlay-close:hover{{color:#e6edf3}}
#overlay-list{{list-style:none;display:flex;flex-direction:column;gap:10px;
              overflow-y:auto;padding:12px 16px 14px}}
.commit-item{{border-top:1px solid #30363d;padding-top:10px}}
.commit-item:first-child{{border-top:none;padding-top:0}}
.commit-meta{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
.commit-hash{{font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
             font-size:11px;color:#58a6ff;text-decoration:none;background:#161b22;
             border:1px solid #30363d;border-radius:4px;padding:1px 5px}}
.commit-hash:hover{{text-decoration:underline}}
.commit-time{{font-size:11px;color:#8b949e}}
.commit-subject{{font-size:12px;color:#c9d1d9;line-height:1.45}}
.commit-subject a{{color:#58a6ff;text-decoration:none}}
.commit-subject a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h1>{repo_display} — Commit Heat Map{gh_link}</h1>
<div class="subtitle">{total_all} commits · {len(authors)} contributor{"s" if len(authors) != 1 else ""} · click any cell to see commits</div>
<div class="legend-strip">{"".join(legend_items)}</div>
{scroll_view}
<div id="overlay" role="dialog" aria-modal="true">
  <div id="overlay-header">
    <div id="overlay-title"></div>
    <button id="overlay-close" aria-label="Close">&#x2715;</button>
  </div>
  <ul id="overlay-list"></ul>
</div>
<script>{js}</script>
</body>
</html>"""

# ── Output ────────────────────────────────────────────────────────────────────

if args.out:
    out_path = args.out
else:
    fd, out_path = tempfile.mkstemp(suffix=".html", prefix=f"heatmap-{repo_display}-")
    os.close(fd)

with open(out_path, "w", encoding="utf-8") as fh:
    fh.write(html)

print(f"Generated: {out_path}")

if not args.no_open:
    webbrowser.open(f"file://{os.path.abspath(out_path)}")
