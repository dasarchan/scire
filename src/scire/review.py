from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path
from .git import pinned_worktree, diff_between, revision, filtered_diff


def gh(args, root: Path, timeout=30):
    result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError(
            "GitHub request failed. Run gh auth login and check repository access. "
            + result.stderr.strip()[-250:]
        )
    return result.stdout


def resolve_review(repo: dict, target: str) -> dict:
    root = Path(repo["path"])
    match = re.fullmatch(r"(?:https://github.com/([^/]+)/([^/]+)/pull/)?([1-9][0-9]*)/?", target)
    if not match:
        return diff_between(repo, target)
    number = match[3]
    if match[1]:
        remote = json.loads(gh(["repo", "view", "--json", "nameWithOwner"], root))["nameWithOwner"]
        if remote.lower() != (match[1] + "/" + match[2]).lower():
            raise ValueError("Select the repository that owns this PR URL")
    info = json.loads(
        gh(
            [
                "pr",
                "view",
                target,
                "--json",
                "number,title,body,url,headRefOid,baseRefOid,headRefName,baseRefName",
            ],
            root,
        )
    )
    path, sha = pinned_worktree(repo, remote_ref=f"refs/pull/{number}/head")
    if sha != info["headRefOid"]:
        raise ValueError("PR head moved while preparing the review. Try again.")
    patch = gh(["pr", "diff", target, "--patch"], root)
    if len(patch.encode()) > 750_000:
        raise ValueError("PR exceeds 750 KB. Review a narrower local range.")
    patch = filtered_diff(patch)
    files = sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.M)))
    return {
        "kind": "pr",
        "number": int(number),
        "title": info["title"],
        "body": info["body"],
        "url": info["url"],
        "head": sha,
        "base": info["baseRefOid"],
        "source": str(path),
        "diff": patch,
        "files": files,
    }


def waiting_reviews(repo: dict) -> list[dict]:
    root = Path(repo["path"])
    waiting = json.loads(
        gh(
            [
                "pr",
                "list",
                "--search",
                "review-requested:@me",
                "--json",
                "number,title,updatedAt,url,headRefOid",
                "--limit",
                "30",
            ],
            root,
        )
    )
    recent = json.loads(
        gh(["pr", "list", "--json", "number,title,updatedAt,url,headRefOid", "--limit", "30"], root)
    )
    ids = {p["number"] for p in waiting}
    return [
        {**p, "waiting": p["number"] in ids}
        for p in waiting + recent
        if p["number"] in ids or not any(w["number"] == p["number"] for w in waiting)
    ]


def head_moved(repo: dict, review: dict) -> bool:
    if review["kind"] == "pr":
        info = json.loads(
            gh(["pr", "view", str(review["number"]), "--json", "headRefOid"], Path(repo["path"]))
        )
        return info["headRefOid"] != review["head"]
    target = review["title"].split("..")[-1]
    return revision(Path(repo["path"]), target) != review["head"]


def changed_line(diff: str, path: str, line: int) -> bool:
    active = False
    current = 0
    for row in diff.splitlines():
        if row.startswith("+++ "):
            active = row[6:] == path
        elif active and row.startswith("@@"):
            match = re.search(r"\+(\d+)", row)
            current = int(match[1]) if match else 0
        elif active and not row.startswith("---"):
            if row.startswith("+"):
                if current == line:
                    return True
                current += 1
            elif row.startswith(" "):
                current += 1
    return False


def post_comment(repo: dict, review: dict, path: str, line: int, body: str):
    if review.get("kind") != "pr":
        raise ValueError("Only GitHub PR reviews can post comments")
    if head_moved(repo, review):
        raise ValueError("PR head changed; refresh the review before posting")
    if not changed_line(review["diff"], path, line):
        raise ValueError("Comment line must be an added line in this pinned PR diff")
    remote = json.loads(gh(["repo", "view", "--json", "nameWithOwner"], Path(repo["path"])))["nameWithOwner"]
    payload = json.dumps(
        {"body": body, "commit_id": review["head"], "path": path, "line": line, "side": "RIGHT"}
    )
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{remote}/pulls/{review['number']}/comments",
            "--method",
            "POST",
            "--input",
            "-",
        ],
        input=payload,
        text=True,
        capture_output=True,
        cwd=repo["path"],
        timeout=30,
    )
    if result.returncode:
        raise ValueError("GitHub rejected the comment; nothing was marked posted.")
    return json.loads(result.stdout)["html_url"]
