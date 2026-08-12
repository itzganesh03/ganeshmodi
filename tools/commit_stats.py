#!/usr/bin/env python3
"""
commit_stats.py — turn a raw git log into the anonymized Development Dashboard
block used in README.md.

It never emits commit hashes, branch names, repository names or ticket IDs.
Those are stripped before any counting happens.

USAGE
-----
Produce a log file from any repo (subjects only, no hashes needed):

    git log --pretty=format:"%s" > mylog.txt

Better — include the year, so you get the per-year curve:

    git log --pretty=format:"%ad|%s" --date=format:"%Y" > mylog.txt

Best — add --numstat, so language share is measured from real changed files
rather than guessed from commit wording:

    git log --pretty=format:"%ad|%s" --date=format:"%Y" --numstat > mylog.txt

Then:

    python tools/commit_stats.py mylog.txt

Paste the printed markdown over the corresponding block in README.md.
Combine several repos by concatenating their logs into one file first.

Only file *extensions* are read from --numstat output. Directory paths are
discarded immediately, so no repository structure is ever revealed.
"""

from __future__ import annotations

import re
import sys
from collections import Counter

# Anything matching these is removed before analysis, so private identifiers
# can never reach the output.
SCRUB = [
    re.compile(r"\b[0-9a-f]{7,40}\b"),               # commit hashes
    re.compile(r"\b(PR|Story|Task|Bug|BugFix|Sprint|Work Item)\s*[:#-]?\s*\d+", re.I),
    re.compile(r"\bhttps?://\S+"),                    # internal URLs
    re.compile(r"\((?:origin/)?[^)]*\)"),             # branch decorations
    re.compile(r"\[[^\]]*\]"),                        # bracketed env/repo tags
]

# theme -> keywords
THEMES = {
    "Validation & input hardening": ["regex", "valid", "sanit", "escap", "param check"],
    "Performance & optimization": ["perform", "optimi", "latency", "throughput", "memory", "cache", "alloc"],
    "Logging & observability": ["log", "trace", "metric", "monitor", "access log"],
    "Revenue & billing correctness": ["revenue", "billing", "cpm", "cpc", "coin", "conversion"],
    "Attribution pipelines": ["attribut", "tracker", "click", "impress"],
    "Capping & rate control": ["capping", "cap ", "throttle", "rate limit", "quota"],
    "Kafka & streaming": ["kafka", "topic", "consumer", "producer", "stream"],
    "Database & storage": ["scylla", "rocksdb", "redis", "mysql", "mongo", "query", "schema", "index"],
    "Release, versioning & sync": ["version", "release", "sync", "merge branch", "revert", "conflict"],
    "Bug fixes & hotfixes": ["fix", "bug", "hotfix", "issue"],
}

LANG_HINTS = {
    "Go": [".go", "golang", "goroutine"],
    "Java": [".java", "spring", "maven", "gradle"],
    "Python": [".py", "python", "pandas"],
    "Config / YAML / Shell": [".yml", ".yaml", ".sh", "dockerfile"],
}

# Extension -> language, used when the log contains --numstat lines.
EXT_LANG = {
    ".go": "Go",
    ".java": "Java", ".kt": "Kotlin",
    ".py": "Python",
    ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "JavaScript", ".tsx": "TypeScript",
    ".sh": "Shell", ".bash": "Shell",
    ".sql": "SQL",
    ".yml": "Config / YAML", ".yaml": "Config / YAML", ".json": "Config / YAML",
    ".toml": "Config / YAML", ".xml": "Config / YAML", ".properties": "Config / YAML",
    ".md": "Docs",
    ".proto": "Protobuf",
    ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++",
    ".html": "HTML", ".css": "CSS",
}

# "12<TAB>3<TAB>path/to/file.go"  — the path is used only to read the extension.
NUMSTAT = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")


def scrub(line: str) -> str:
    for pattern in SCRUB:
        line = pattern.sub(" ", line)
    return re.sub(r"\s+", " ", line).strip()


def bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def main(path: str) -> None:
    raw = [ln for ln in open(path, encoding="utf-8", errors="replace").read().splitlines() if ln.strip()]

    years: Counter[str] = Counter()
    subjects: list[str] = []
    ext_lines: Counter[str] = Counter()   # language -> lines changed

    for line in raw:
        numstat = NUMSTAT.match(line)
        if numstat:
            added, deleted, path = numstat.groups()
            # Keep the extension only; the path itself is dropped here.
            dot = path.rfind(".")
            lang = EXT_LANG.get(path[dot:].lower()) if dot != -1 else None
            if lang:
                churn = sum(int(v) for v in (added, deleted) if v.isdigit())
                ext_lines[lang] += max(churn, 1)
            continue

        if "|" in line[:6]:
            year, _, rest = line.partition("|")
            if year.strip().isdigit():
                years[year.strip()] += 1
            line = rest
        subjects.append(scrub(line))

    total = len(subjects)
    if not total:
        sys.exit("No commits found in that file.")

    merged = sum(1 for s in subjects if re.search(r"\bmerged\b", s, re.I))

    theme_counts: Counter[str] = Counter()
    for s in subjects:
        low = s.lower()
        for theme, keys in THEMES.items():
            if any(k in low for k in keys):
                theme_counts[theme] += 1

    lang_counts: Counter[str] = Counter()
    for s in subjects:
        low = s.lower()
        for lang, keys in LANG_HINTS.items():
            if any(k in low for k in keys):
                lang_counts[lang] += 1

    out: list[str] = []
    add = out.append

    add("### Recent Sample Window\n")
    add("<table>\n<tr>")
    add(f"<td align=\"center\"><h3>{total}</h3><sub>Commits analysed</sub></td>")
    add(f"<td align=\"center\"><h3>{merged}</h3><sub>Reviewed PRs merged</sub></td>")
    add(f"<td align=\"center\"><h3>{round(merged / total * 100)}%</h3><sub>Merged via code review</sub></td>")
    add(f"<td align=\"center\"><h3>{len(years) or '—'}</h3><sub>Years covered</sub></td>")
    add("</tr>\n</table>\n")

    add("### Contribution Themes\n")
    add("| Theme | Share | Distribution |")
    add("|:--|:--|:--|")
    for theme, count in theme_counts.most_common():
        pct = count / total * 100
        add(f"| {theme} | {pct:.0f}% | `{bar(pct)}` |")
    add("")

    # Prefer real file-extension data from --numstat; fall back to keyword guessing.
    measured = bool(ext_lines)
    source = ext_lines if measured else lang_counts
    if source:
        label = "measured from changed files" if measured else "estimated from commit wording"
        add(f"### Language Distribution ({label})\n")
        add("| Language | Share | Bar |")
        add("|:--|:--|:--|")
        lang_total = sum(source.values())
        for lang, count in source.most_common(8):
            pct = count / lang_total * 100
            add(f"| {lang} | {pct:.0f}% | `{bar(pct)}` |")
        add("")
        if not measured:
            add("<sub><i>Re-run with <code>--numstat in the git log for accurate figures.</i></sub>\n")

    if years:
        add("### Yearly Activity Curve\n")
        add("```")
        add(" Commits (relative intensity)")
        peak = max(years.values())
        for year in sorted(years):
            add(f" {year}  {bar(years[year] / peak * 100)}  {years[year]} commits")
        add("```")

    print("\n".join(out))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])</code>
