from __future__ import annotations
import re
import subprocess
from pathlib import Path
from .paths import home, SECRET_NAME, EXCLUDED


def git(root: Path, *args: str, timeout=30) -> str:
    if any("\0" in str(a) for a in args):
        raise ValueError("Invalid Git argument")
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "diff.external=",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip()[-1000:] or "Git command failed")
    return result.stdout


def revision(root: Path, ref="HEAD") -> str:
    if ref.startswith("-") or not re.fullmatch(r"[\w./@{}~^+-]+", ref):
        raise ValueError("Invalid revision")
    value = git(root, "rev-parse", "--verify", ref + "^{commit}").strip()
    if not re.fullmatch(r"[a-f0-9]{40,64}", value):
        raise ValueError("Could not resolve a commit")
    return value


def default_ref(root: Path) -> str:
    try:
        return git(root, "symbolic-ref", "refs/remotes/origin/HEAD").strip()
    except ValueError:
        for name in ("main", "master", "HEAD"):
            try:
                revision(root, name)
                return name
            except ValueError:
                continue
    raise ValueError("Repository has no commits")


def pinned_worktree(repo: dict, ref: str | None = None, remote_ref: str | None = None) -> tuple[Path, str]:
    """All Git mutations go into our independent mirror, never source/.git."""
    source = Path(repo["path"])
    base = home() / "repos" / repo["id"]
    mirror = base / "mirror.git"
    base.mkdir(parents=True, exist_ok=True)
    if not mirror.exists():
        subprocess.run(
            ["git", "clone", "--bare", "--no-hardlinks", str(source), str(mirror)],
            check=True,
            capture_output=True,
            timeout=90,
        )
    else:
        git(mirror, "fetch", "--no-tags", str(source), "+refs/heads/*:refs/heads/*", timeout=90)
    if remote_ref:
        remote = git(source, "remote", "get-url", "origin").strip()
        import shutil

        options = (
            ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
            if "github.com/" in remote and shutil.which("gh")
            else []
        )
        git(mirror, *options, "fetch", "--no-tags", remote, remote_ref, timeout=90)
        sha = revision(mirror, "FETCH_HEAD")
    else:
        chosen = ref or default_ref(source)
        sha = revision(source, chosen)
        try:
            revision(mirror, sha)
        except ValueError:
            git(mirror, "fetch", str(source), sha, timeout=90)
    path = base / "worktrees" / sha
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        git(mirror, "worktree", "add", "--detach", str(path), sha, timeout=90)
    return path, sha


def diff_between(repo: dict, target: str) -> dict:
    source = Path(repo["path"])
    if ".." in target:
        parts = re.split(r"\.{2,3}", target)
        if len(parts) != 2:
            raise ValueError("Use base..head or base...head")
        base, head = parts
    else:
        base, head = default_ref(source), target
    head_sha = revision(source, head)
    base_sha = revision(source, base)
    if "..." in target:
        base_sha = git(source, "merge-base", base_sha, head_sha).strip()
    path, _ = pinned_worktree(repo, head)
    patch = git(source, "diff", "--no-ext-diff", "--no-textconv", base_sha, head_sha, "--")
    if len(patch.encode()) > 750_000:
        raise ValueError("Diff exceeds 750 KB; select a narrower range")
    patch = filtered_diff(patch)
    if not patch.strip():
        raise ValueError("This target has no eligible code changes")
    files = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.M)))
    return {
        "kind": "branch",
        "title": target,
        "head": head_sha,
        "base": base_sha,
        "source": str(path),
        "diff": patch,
        "files": files,
    }


def filtered_diff(patch: str) -> str:
    """Exclude secret/dotfile blocks before a diff reaches inference."""
    blocks = re.split(r"(?=^diff --git )", patch, flags=re.M)
    kept = []
    for block in blocks:
        paths = re.findall(r"^(?:--- a/|\+\+\+ b/)(.+)$", block, re.M)
        if not paths:
            continue
        if any(
            any(
                part in {"..", "."} or SECRET_NAME.search(part) or part in EXCLUDED
                for part in Path(name).parts
            )
            for name in paths
        ):
            continue
        if re.search(r"-----BEGIN .*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}", block):
            continue
        kept.append(block)
    return "".join(kept)
