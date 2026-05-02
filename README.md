# git-heatmap

A GitHub-style commit heat map for any git repository. Shows each contributor's activity as a calendar grid — stacked so you can compare contributors at a glance — with blank stretches collapsed year by year. Click any cell to see the commits for that day.

![Heat map showing stacked contributor rows with colored cells by activity level](https://github.com/waviisoft/git-heatmap/assets/placeholder/screenshot.png)

## Features

- **Stacked contributors** — all authors share the same time axis so activity patterns are directly comparable
- **Blank space collapsed** — each year section shows only the weeks around actual commits, keeping the view compact
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
|------|-------------|
| `--out <file>` | Write HTML to a specific path instead of a temp file |
| `--no-open` | Generate the file without opening it in a browser |

### Examples

```bash
# Generate and open immediately (default)
python3 git-heatmap.py

# Save to a specific file
python3 git-heatmap.py --out ~/Desktop/my-repo-heatmap.html

# Generate for another repo without opening
python3 git-heatmap.py /path/to/other-repo --no-open --out other-repo.html
```

## How it works

1. Runs `git log` to collect every commit's hash, timestamp, author, and subject
2. Builds a calendar grid from the repo's first commit to its last, grouped by author
3. Collapses each year to show only the active date range (± 2 weeks of padding)
4. Renders a dark-themed HTML file with inline SVG grids and embedded commit data
5. Commit messages are linkified: `#123` → issue/PR on the same GitHub repo; `org/repo#123` → cross-repo link

## License

MIT
