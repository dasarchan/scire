"""Local, read-only Git discovery and terminal repository selection."""

from __future__ import annotations

import os
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import questionary

from .store import Store

# Avoid generated trees, application bundles and personal media during a home scan.
SKIP = {
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "target",
    "venv",
    "env",
    "site-packages",
    "library",
    "applications",
    "pictures",
    "photos",
    "movies",
    "music",
    "$recycle.bin",
    "system volume information",
}
PRIORITY = {
    "desktop",
    "developer",
    "development",
    "projects",
    "code",
    "src",
    "work",
    "repos",
    "github",
    "documents",
}
BROWSE = "__scire_browse__"
STYLE = questionary.Style(
    [
        ("qmark", "fg:#79a8ff"),
        ("question", "bold"),
        ("answer", "fg:#79a8ff"),
        ("pointer", "fg:#79a8ff bold"),
        ("highlighted", "fg:#79a8ff bold"),
        ("selected", "fg:#79a8ff"),
        ("instruction", "fg:#919aa9"),
    ]
)


@dataclass(frozen=True)
class Discovery:
    repos: tuple[Path, ...]
    visited: int
    skipped: int
    limited: bool
    seconds: float


def is_repo(path: Path) -> bool:
    """Recognize working repositories and linked worktrees without running Git."""
    marker = path / ".git"
    try:
        if marker.is_dir():
            return (marker / "HEAD").is_file()
        if marker.is_file():
            with marker.open() as stream:
                line = stream.readline(4096).strip()
            if line.startswith("gitdir: "):
                git_dir = (path / line[8:]).resolve()
                return (git_dir / "HEAD").is_file()
    except (OSError, UnicodeError, RuntimeError):
        pass
    return False


def default_roots() -> list[Path]:
    user_home = Path.home().resolve()
    cwd = Path.cwd().resolve()
    current = next((p for p in [cwd, *cwd.parents] if is_repo(p)), None)
    roots = [user_home]
    if current:
        roots.insert(0, current)
    elif cwd != Path(cwd.anchor) and not cwd.is_relative_to(user_home):
        roots.insert(0, cwd)
    return roots


def eligible_directory(entry: os.DirEntry) -> bool:
    name = entry.name.casefold()
    return (
        not name.startswith(".")
        and name not in SKIP
        and not name.endswith((".app", ".bundle", ".framework", ".photoslibrary"))
        and entry.is_dir(follow_symlinks=False)
    )


def discover_repos(roots=None, *, max_seconds=8, max_directories=30_000, max_depth=8) -> Discovery:
    """Bound breadth-first traversal; stop at repositories and never follow links."""
    started = time.monotonic()
    queue = deque((Path(p).expanduser(), 0) for p in (default_roots() if roots is None else roots))
    seen, found = set(), set()
    skipped, limited = 0, False
    while queue:
        if len(seen) >= max_directories or time.monotonic() - started >= max_seconds:
            limited = True
            break
        path, depth = queue.popleft()
        try:
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            if is_repo(path):
                found.add(path)
                continue
            with os.scandir(path) as entries:
                children = []
                for entry in entries:
                    try:
                        if eligible_directory(entry):
                            children.append(Path(entry.path))
                    except OSError:
                        skipped += 1
            if depth >= max_depth:
                limited |= bool(children)
                continue
            children.sort(key=lambda p: (p.name.casefold() not in PRIORITY, p.name.casefold()))
            queue.extend((child, depth + 1) for child in children)
        except (OSError, RuntimeError):
            skipped += 1
    return Discovery(
        tuple(sorted(found, key=lambda p: str(p).casefold())),
        len(seen),
        skipped,
        limited,
        round(time.monotonic() - started, 3),
    )


def terminal_text(value: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "?", value)


def location(path: Path) -> str:
    try:
        relative = path.relative_to(Path.home())
        text = "~" if relative == Path(".") else "~/" + str(relative)
    except ValueError:
        text = str(path)
    return terminal_text(text)


def repository_prompt(paths, selected, **terminal_options):
    """Build a searchable checkbox prompt; terminal adapters also support testing."""
    ordered = sorted(paths, key=lambda p: (p not in selected, p.name.casefold(), str(p)))
    choices = [
        questionary.Choice(
            f"{terminal_text(p.name)}  ·  {location(p)}" + ("  [connected]" if p in selected else ""),
            value=str(p),
            checked=p in selected,
        )
        for p in ordered
    ]
    choices += [questionary.Separator(), questionary.Choice("Search another folder…", value=BROWSE)]
    return questionary.checkbox(
        "Which repositories would you like to connect?",
        choices=choices,
        style=STYLE,
        use_search_filter=True,
        use_jk_keys=False,
        instruction="\n  ↑/↓ move · Space select · type to search · Enter connect · Ctrl-C cancel",
        validate=lambda values: bool(values) or "Select a repository, or search another folder.",
        **terminal_options,
    )


def browse_folder(start=None):
    """Choose a search folder by navigation, without entering a filesystem path."""
    current = Path(start or Path.home()).expanduser().resolve()
    show_hidden = False
    while True:
        try:
            with os.scandir(current) as entries:
                children = sorted(
                    (
                        Path(e.path)
                        for e in entries
                        if (show_hidden or not e.name.startswith(".")) and e.is_dir()
                    ),
                    key=lambda p: p.name.casefold(),
                )
        except OSError:
            children = []
        choices = [questionary.Choice("Search this folder", value=("search", current))]
        if current.parent != current:
            choices.append(questionary.Choice("↑ Parent folder", value=("open", current.parent)))
        choices += [questionary.Choice("▸ " + location(p), value=("open", p)) for p in children]
        choices.append(
            questionary.Choice(
                "Hide hidden folders" if show_hidden else "Show hidden folders", value=("hidden", None)
            )
        )
        choices.append(questionary.Choice("Back to repositories", value=("back", None)))
        action, path = questionary.select(
            "Look in " + location(current),
            choices=choices,
            style=STYLE,
            use_search_filter=True,
            use_jk_keys=False,
            instruction="(↑/↓ move · type to search · Enter choose)",
        ).unsafe_ask(patch_stdout=True)
        if action == "search":
            return path
        if action == "back":
            return None
        if action == "hidden":
            show_hidden = not show_hidden
        else:
            current = path.resolve()


def connect_repositories(store=None):
    store = store or Store()
    selected = {Path(r["path"]) for r in store.repos()}
    print("\nScire · Connect your repositories\n")
    print("Looking for Git repositories in your folders…", flush=True)
    result = discover_repos([*default_roots(), *selected])
    paths = set(result.repos)
    print(f"Found {len(paths)} repositories in {result.seconds:.1f}s. Existing connections are selected.\n")
    if result.limited:
        print("Showing results so far. Search another folder to find more.\n")
    while True:
        values = repository_prompt(paths, selected).unsafe_ask(patch_stdout=True)
        selected = {Path(value) for value in values if value != BROWSE}
        if BROWSE in values:
            folder = browse_folder()
            if folder:
                print("Looking for Git repositories in " + location(folder) + "…", flush=True)
                result = discover_repos([folder])
                paths.update(result.repos)
                print(f"Found {len(result.repos)} repositories.\n")
            continue
        repos = store.set_repos(selected)
        print(f"\nConnected {len(repos)} repositor" + ("y." if len(repos) == 1 else "ies."))
        print("Run scire setup again whenever you want to change this selection.\n")
        return repos


def choose_connected_repo(repos):
    rid = questionary.select(
        "Which repository?",
        choices=[
            questionary.Choice(terminal_text(r["name"]) + "  ·  " + location(Path(r["path"])), value=r["id"])
            for r in repos
        ],
        style=STYLE,
        use_search_filter=True,
        use_jk_keys=False,
    ).unsafe_ask(patch_stdout=True)
    return next(r for r in repos if r["id"] == rid)
