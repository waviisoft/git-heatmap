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

ALIAS: dict[str, str] = {}   # add known aliases here if needed

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

PADDING_WEEKS = 2

def active_range_for_year(year: int):
    active = []
    for wi, week in enumerate(all_weeks):
        for d in week:
            if d.year == year:
                for a in authors:
                    if commit_counts[a].get(d.isoformat(), 0) > 0:
                        active.append(wi)
                        break
    if not active:
        return None
    return (max(0, min(active) - PADDING_WEEKS),
            min(len(all_weeks) - 1, max(active) + PADDING_WEEKS))

# ── SVG generation ────────────────────────────────────────────────────────────

CELL = 10; GAP = 2; STEP = CELL + GAP
LABEL_W = 26; DAY_LABEL_W = 10; LEFT = LABEL_W + DAY_LABEL_W
TOP = 18; AUTHOR_GAP = 10
MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_CHARS = "SMTWTFS"

def commit_level(count: int) -> int:
    if count == 0: return 0
    if count == 1: return 1
    if count <= 3: return 2
    if count <= 5: return 3
    return 4


def make_stacked_svg(wi_range: tuple[int, int]) -> str:
    week_slice = all_weeks[wi_range[0]: wi_range[1] + 1]
    nw = len(week_slice)
    author_h = 7 * STEP
    total_h = TOP + len(authors) * author_h + (len(authors) - 1) * AUTHOR_GAP + 6
    width = LEFT + nw * STEP + 4

    lines = [f'<svg width="{width}" height="{total_h}" xmlns="http://www.w3.org/2000/svg">']

    # Month labels
    seen_months: set = set()
    for col, week in enumerate(week_slice):
        for d in week:
            key = (d.year, d.month)
            if d.day <= 7 and key not in seen_months:
                seen_months.add(key)
                x = LEFT + col * STEP
                lines.append(f'<text x="{x}" y="{TOP - 4}" font-size="9" fill="#8b949e">'
                              f'{MONTH_NAMES[d.month]}</text>')

    for ai, author in enumerate(authors):
        meta = AUTHOR_META[author]
        ay = TOP + ai * (author_h + AUTHOR_GAP)

        # Separator line
        if ai > 0:
            sep_y = ay - AUTHOR_GAP // 2
            lines.append(f'<line x1="{LEFT}" y1="{sep_y}" x2="{LEFT + nw * STEP}" y2="{sep_y}" '
                         f'stroke="#30363d" stroke-width="1"/>')

        # Author initials label
        mid_y = ay + author_h // 2 + 4
        lines.append(f'<text x="0" y="{mid_y}" font-size="9" font-weight="700" '
                     f'fill="{meta["accent"]}">{meta["initials"]}</text>')

        # M/W/F day labels
        for di, ch in enumerate(DAY_CHARS):
            if di in (1, 3, 5):
                y = ay + di * STEP + CELL - 1
                lines.append(f'<text x="{LABEL_W}" y="{y}" font-size="9" fill="#656d76">{ch}</text>')

        # Cells
        for col, week in enumerate(week_slice):
            for di, d in enumerate(week):
                cnt = commit_counts[author].get(d.isoformat(), 0)
                fill = meta["palette"][commit_level(cnt)]
                x = LEFT + col * STEP
                y = ay + di * STEP
                date_label = d.strftime("%b %-d, %Y")
                tip = f"{cnt} commit{'s' if cnt != 1 else ''} on {date_label}"
                data = (f'data-author="{author}" data-date="{d.isoformat()}" '
                        f'data-count="{cnt}" data-label="{date_label}"')
                cursor = 'style="cursor:pointer"' if cnt > 0 else ""
                lines.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                             f'fill="{fill}" {data} {cursor} class="cell">'
                             f'<title>{tip}</title></rect>')

    lines.append("</svg>")
    return "\n".join(lines)

# ── Build year sections ───────────────────────────────────────────────────────

year_totals: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
for a in authors:
    for ds, cnt in commit_counts[a].items():
        year_totals[int(ds[:4])][a] += cnt

all_years = sorted(year_totals.keys(), reverse=True)

sections_html = []
for year in all_years:
    rng = active_range_for_year(year)
    if rng is None:
        continue
    svg = make_stacked_svg(rng)
    nweeks = rng[1] - rng[0] + 1
    total_yr = sum(year_totals[year].values())

    badges = []
    for a in authors:
        n = year_totals[year].get(a, 0)
        if n == 0:
            continue
        color = AUTHOR_META[a]["accent"]
        ini = AUTHOR_META[a]["initials"]
        badges.append(
            f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;">'
            f'<span style="width:10px;height:10px;border-radius:50%;background:{color};'
            f'display:inline-block;"></span>'
            f'<span style="color:#8b949e;font-size:12px;">{ini} '
            f'<strong style="color:#c9d1d9">{n}</strong></span></span>'
        )

    sparse = total_yr <= 3 and year < (all_years[-1] + 2)
    label_suffix = (" <span style='font-size:11px;color:#484f58;font-weight:400;'>"
                    "— sparse</span>") if sparse else ""

    sections_html.append(f"""
<div class="year-section">
  <div class="year-header">
    <span class="year-label">{year}{label_suffix}</span>
    <span class="year-badges">{"".join(badges)}</span>
    <span class="year-meta">{nweeks} weeks shown · {total_yr} commit{"s" if total_yr != 1 else ""}</span>
  </div>
  <div class="heatmap-scroll">{svg}</div>
</div>""")

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
  const cell = e.target.closest('rect.cell');
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
.year-section{{margin-bottom:20px}}
.year-header{{display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap}}
.year-label{{font-size:13px;font-weight:700;color:#e6edf3;min-width:48px}}
.year-badges{{display:flex;align-items:center;flex-wrap:wrap}}
.year-meta{{font-size:11px;color:#484f58;margin-left:auto}}
.heatmap-scroll{{overflow-x:auto;background:#161b22;border:1px solid #30363d;
                border-radius:6px;padding:12px 12px 8px}}
.heatmap-scroll svg{{display:block}}
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
{"".join(sections_html)}
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
