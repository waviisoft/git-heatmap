# git-heatmap

A GitHub-style commit heat map for any git repository. Shows each contributor's activity as a calendar grid — stacked so you can compare contributors at a glance — in a single unified timeline you can scroll through. Click any cell to see the commits for that day.

![Heat map showing stacked contributor rows with colored cells by activity level](https://github.com/waviisoft/git-heatmap/assets/placeholder/screenshot.png)

## Features

- **Unified horizontal scroll** — all years form one continuous timeline; most recent activity is on the left, oldest on the right
- **Sticky author column** — each contributor is represented by a colour-coded avatar that stays pinned to the left as you scroll
- **Sticky month/year headers** — month and year labels stay anchored at the top so you always know where you are in the timeline; year boundaries are visually separated
- **Compact grid** — weeks with no commits are hidden; each year with activity shows at least 3 weeks and each active month shows at least 2, so sparse histories stay readable without wasted space
- **Stacked contributors** — all authors share the same time axis so activity patterns are directly comparable
- **Clickable cells** — click any cell to see an overlay with each commit's short hash (linked to GitHub), timestamp, and message
- **Smart issue/PR linking** — `#123` in a commit message links to the same repo; `org/repo#123` links cross-repo
- **Auto-detected GitHub remote** — commit and issue links are generated automatically from the `origin` remote
- **Up to 8 contributors** — each assigned a distinct colour palette
- **No dependencies** — pure Python standard library; outputs a self-contained HTML file

## Requirements

- Python 3.9+
- Git

## Usage

Run from inside any git repository:

```bash
python3 git-heatmap.py
```

Or point it at a repo elsewhere:

```bash
python3 git-heatmap.py /path/to/repo
```

The script generates a self-contained HTML file and opens it in your default browser.

### Options

| Flag | Description |
| ---- | ----------- |
| `--out <file>` | Write HTML to a specific path instead of a temp file |
| `--no-open` | Generate the file without opening it in a browser |
| `--merge PRIMARY:alt1,alt2` | Merge author names into one (repeatable) |
| `--config <file>` | Path to a `.git-heatmap.json` config file |

### Examples

```bash
# Generate and open immediately (default)
python3 git-heatmap.py

# Save to a specific file
python3 git-heatmap.py --out ~/Desktop/my-repo-heatmap.html

# Generate for another repo without opening
python3 git-heatmap.py /path/to/other-repo --no-open --out other-repo.html

# Merge duplicate author identities
python3 git-heatmap.py --merge "Jane Doe:jane,j.doe@example.com"
```

### Author merging

If the same person has committed under different names or emails, use `--merge` or a config file to combine them:

**CLI flag** (repeatable):

```bash
python3 git-heatmap.py --merge "Jane Doe:jane,j.doe" --merge "Bob:robert,rob"
```

**Config file** (`.git-heatmap.json` in the repo root, or `--config <path>`):

```json
{
  "merge_authors": {
    "Jane Doe": ["jane", "j.doe"],
    "Bob":      ["robert", "rob"]
  }
}
```

## How it works

1. Runs `git log` to collect every commit's hash, timestamp, author, and subject
2. Builds a single calendar grid spanning the entire commit history, newest week first
3. Renders a dark-themed HTML file with an interactive table and embedded commit data
4. Commit messages are linkified: `#123` → issue/PR on the same GitHub repo; `org/repo#123` → cross-repo link

## License

MIT
