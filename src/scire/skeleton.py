from __future__ import annotations
import ast
import collections
import hashlib
import math
import re
from pathlib import Path
import pathspec
from .git import git
from .paths import EXCLUDED, SECRET_NAME, safe_source

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".swift",
    ".kt",
    ".md",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".rst",
    ".txt",
    ".ini",
    ".cfg",
}


def source_files(root: Path, limit=4000) -> list[str]:
    try:
        names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    except ValueError:
        names = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    rules = pathspec.PathSpec.from_lines(
        "gitwildmatch",
        (root / ".gitignore").read_text().splitlines() if (root / ".gitignore").exists() else [],
    )
    result = []
    for name in sorted(set(names)):
        p = Path(name)
        if not name or len(result) >= limit or any(SECRET_NAME.search(x) or x in EXCLUDED for x in p.parts):
            continue
        if p.suffix not in TEXT_SUFFIXES and p.name not in {"Makefile", "Dockerfile", "LICENSE"}:
            continue
        if rules.match_file(name):
            continue
        try:
            safe_source(root, name)
        except (ValueError, OSError, UnicodeError):
            continue
        result.append(name)
    return result


def build_skeleton(root: Path) -> dict:
    files = source_files(root)
    units, symbols, imports, headings, entries = [], [], [], [], []
    symbol_uses = collections.Counter()
    fingerprints = {}
    for name in files:
        text = safe_source(root, name).read_text()
        fingerprints[name] = hashlib.sha256(text.encode()).hexdigest()
        units.append(
            {
                "path": name,
                "language": Path(name).suffix.lstrip("."),
                "lines": len(text.splitlines()),
                "root": name.split("/")[0],
            }
        )
        symbol_uses.update(re.findall(r"\b[A-Za-z_]\w{2,}\b", text))
        if Path(name).suffix == ".py":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            {
                                "name": node.name,
                                "path": name,
                                "line": node.lineno,
                                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                            }
                        )
                    elif isinstance(node, ast.Import):
                        imports.extend({"from": name, "root": a.name.split(".")[0]} for a in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append({"from": name, "root": node.module.split(".")[0]})
            except SyntaxError:
                pass
        else:
            for match in re.finditer(r"\b(class|function|interface|struct|fn|func)\s+(\w+)", text):
                symbols.append(
                    {
                        "name": match[2],
                        "kind": match[1],
                        "path": name,
                        "line": text.count("\n", 0, match.start()) + 1,
                    }
                )
            for match in re.finditer(r"(?:from\s+|import\s*\(?|require\()['\"]([^'\"]+)", text):
                imports.append({"from": name, "root": match[1].split("/")[0]})
        if name.endswith((".md", ".rst")):
            headings.extend(
                {"path": name, "title": line.lstrip("# ")}
                for line in text.splitlines()
                if line.startswith("#")
            )
            if name.endswith(".rst"):
                rows = text.splitlines()
                headings.extend(
                    {"path": name, "title": rows[i - 1]}
                    for i, line in enumerate(rows)
                    if i and len(line) > 2 and set(line) <= set("=-~^") and rows[i - 1].strip()
                )
        if (
            Path(name).name
            in {"__main__.py", "main.py", "app.py", "main.go", "main.rs", "index.ts", "index.js", "cli.py"}
            or '__name__ == "__main__"' in text
            or "[project.scripts]" in text
        ):
            entries.append(name)
    # Reference-weighted graph centrality, inspired by repository-map ranking rather
    # than a plain list of definitions. Imports contribute edges between units.
    roots = collections.defaultdict(list)
    for unit in units:
        roots[Path(unit["path"]).stem].append(unit["path"])
        roots[unit["root"]].append(unit["path"])
    edges = collections.defaultdict(set)
    for item in imports:
        edges[item["from"]].update(roots.get(item["root"], [])[:20])
    rank = {name: 1 / max(1, len(files)) for name in files}
    for _ in range(12):
        next_rank = {name: 0.15 / max(1, len(files)) for name in files}
        for name, links in edges.items():
            for target in links:
                if target in next_rank:
                    next_rank[target] += 0.85 * rank.get(name, 0) / max(1, len(links))
        rank = next_rank
    for item in symbols:
        item["rank"] = round(rank.get(item["path"], 0) * 100 + math.log1p(symbol_uses[item["name"]]), 4)
    symbols.sort(key=lambda x: x["rank"], reverse=True)
    hot = collections.Counter()
    pairs = collections.Counter()
    try:
        history = git(root, "log", "-80", "--format=COMMIT", "--name-only", "--no-renames")
        for block in history.split("COMMIT"):
            changed = sorted(set(line.strip() for line in block.splitlines() if line.strip() in fingerprints))
            hot.update(changed)
            if len(changed) <= 15:
                for i, first in enumerate(changed):
                    for second in changed[i + 1 :]:
                        pairs[(first, second)] += 1
    except ValueError:
        pass
    return {
        "version": 1,
        "file_count": len(files),
        "units": units,
        "imports": imports[:2000],
        "central_definitions": symbols[:120],
        "entry_points": entries[:30],
        "doc_headings": headings[:80],
        "hot_files": [{"path": k, "changes": v} for k, v in hot.most_common(30)],
        "co_change": [{"files": list(k), "commits": v} for k, v in pairs.most_common(40)],
        "fingerprints": fingerprints,
        "fingerprint": hashlib.sha256(
            "".join(f"{k}:{v}" for k, v in fingerprints.items()).encode()
        ).hexdigest(),
    }
