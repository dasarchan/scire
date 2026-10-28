from __future__ import annotations
import asyncio
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .agent import opencode_binary
from .git import git, default_ref
from .knowledge import Knowledge
from .paths import home, read_json, write_json
from .store import Store
from . import __version__

REPOSITORY = "https://github.com/dasarchan/scire.git"


def available_models():
    result = subprocess.run(
        [opencode_binary(), "models", "--pure"], capture_output=True, text=True, timeout=40, cwd=home()
    )
    if result.returncode:
        raise ValueError("OpenCode could not list models. Run scire setup --connect.")
    return sorted(
        set(row.strip() for row in result.stdout.splitlines() if re.fullmatch(r"[\w.-]+/[^\s]+", row.strip()))
    )


def connect(model=None):
    # Native provider selection, browser OAuth, or key entry stays inside OpenCode.
    result = subprocess.run([opencode_binary(), "auth", "login", "--pure"], cwd=home())
    if result.returncode:
        raise ValueError("OpenCode login did not complete")
    return select_model(model)


def select_model(model=None):
    models = available_models()
    providers = sorted({m.split("/")[0] for m in models})
    print("Available providers: " + ", ".join(providers))
    chosen = model or input("Model (provider/model, or provider to list its models): ").strip()
    while chosen in providers:
        print("\n".join(m for m in models if m.startswith(chosen + "/")))
        chosen = input("Model (provider/model): ").strip()
    if not chosen or "/" not in chosen:
        raise ValueError("Choose a model as provider/model")
    store = Store()
    profile = store.profile()
    profile["model"] = chosen
    store.save_profile(profile)
    print("Scire will use " + chosen)


def doctor():
    checks = []
    for binary in ("git", "gh", "uv"):
        checks.append(
            (
                binary,
                shutil.which(binary) or ("optional — GitHub PR features" if binary == "gh" else "missing"),
            )
        )
    try:
        checks.append(("OpenCode", opencode_binary()))
    except ValueError:
        checks.append(("OpenCode", "missing — install https://opencode.ai"))
    checks.append(("Python", sys.version.split()[0]))
    checks.append(("State", str(home())))
    checks.append(("Model", Store().profile().get("model") or "not selected — scire setup --connect"))
    for name, value in checks:
        print(f"{name:12} {value}")
    try:
        version = subprocess.run([opencode_binary(), "--version"], capture_output=True, text=True, timeout=10)
        print("OpenCode ver " + version.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    return all(not value.startswith("missing") for _, value in checks)


def receipt_source():
    roots = [Path(sys.prefix)]
    uv = shutil.which("uv")
    if uv:
        result = subprocess.run([uv, "tool", "dir"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            roots.append(Path(result.stdout.strip()) / "scire-local")
    import tomllib

    for root in roots:
        file = root / "uv-receipt.toml"
        if not file.exists():
            continue
        value = tomllib.loads(file.read_text())
        for requirement in value.get("tool", {}).get("requirements", []):
            for key in ("git", "url", "directory", "path"):
                if requirement.get(key):
                    return str(requirement[key])
    return None


def update_source():
    source = receipt_source()
    if not source:
        return REPOSITORY
    if re.search(r"\.(whl|tar\.gz)(?:[?#].*)?$", source):
        return REPOSITORY
    if source.startswith("git+"):
        source = source[4:]
    if source.startswith(("http://", "https://", "ssh://", "git@")):
        return re.sub(r"(?<=\.git)@[^/]+$", "", source.split("#")[0].split("?")[0])
    candidate = Path(source.removeprefix("file://")).expanduser()
    if candidate.exists():
        try:
            return git(candidate, "remote", "get-url", "origin").strip()
        except ValueError:
            pass
    raise ValueError(
        "Cannot determine a Git update source from the uv receipt. Reinstall from the Scire Git repository."
    )


def git_environment(source):
    env = dict(os.environ)
    if "github.com/" in source and shutil.which("gh"):
        offset = int(env.get("GIT_CONFIG_COUNT", "0"))
        for index, value in enumerate(["", "!gh auth git-credential"], offset):
            env["GIT_CONFIG_KEY_" + str(index)] = "credential.https://github.com.helper"
            env["GIT_CONFIG_VALUE_" + str(index)] = value
        env["GIT_CONFIG_COUNT"] = str(offset + 2)
    return env


def newest_tag(source=None):
    source = source or update_source()
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", source, "v*"],
        capture_output=True,
        text=True,
        timeout=15,
        env=git_environment(source),
    )
    if result.returncode:
        raise ValueError("Could not check releases; verify Git repository access")
    tags = re.findall(r"refs/tags/v(\d+)\.(\d+)\.(\d+)\s*$", result.stdout, re.M)
    return max((tuple(map(int, t)) for t in tags), default=None)


def check_updates():
    path = home() / "update.json"
    state = read_json(path, {})
    if time.time() - state.get("checked_at", 0) < 86400:
        return
    try:
        latest = newest_tag()
        write_json(path, {"checked_at": time.time(), "latest": latest})
        if latest and latest > tuple(map(int, __version__.split("."))):
            print("Scire " + ".".join(map(str, latest)) + " is available. Run scire update.", file=sys.stderr)
    except (ValueError, OSError, subprocess.SubprocessError):
        write_json(path, {"checked_at": time.time()})


def update():
    source = update_source()
    tag = newest_tag(source)
    if not tag:
        raise ValueError("No vX.Y.Z release tags found")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required for updates")
    print("Installing Scire " + ".".join(map(str, tag)) + " from latest…")
    subprocess.run(
        [
            uv,
            "tool",
            "install",
            "--force",
            "--reinstall",
            "--refresh",
            "--python",
            "3.11",
            "git+" + source + "@latest",
        ],
        check=True,
        env=git_environment(source),
    )


def install_skill(dest=None):
    target = Path(dest).expanduser() if dest else Path.home() / ".claude/skills/scire"
    target.mkdir(parents=True, exist_ok=True)
    bundled = Path(__file__).parent / "skill/SKILL.md"
    (target / "SKILL.md").write_text(bundled.read_text())
    print("Installed " + str(target / "SKILL.md"))
    return target


def schedule_digest():
    if sys.platform != "darwin":
        raise ValueError("--schedule currently supports macOS LaunchAgents")
    executable = shutil.which("scire")
    if not executable:
        raise ValueError("Install Scire with uv tool install before scheduling")
    directory = Path.home() / "Library/LaunchAgents"
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / "ai.scire.digest.plist"
    log = home() / "digest.log"
    value = {
        "Label": "ai.scire.digest",
        "ProgramArguments": [executable, "digest", "--no-open"],
        "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        "RunAtLoad": False,
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SCIRE_HOME": str(home())},
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    file.write_bytes(plistlib.dumps(value))
    file.chmod(0o600)
    domain = "gui/" + str(os.getuid())
    subprocess.run(["launchctl", "bootout", domain, str(file)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(file)], check=True)
    print("Weekly digest scheduled for Mondays at 9:00. " + str(file))


async def build_digest(service):
    store = service.store
    items = []
    roots = []
    for repo in store.repos():
        m = read_json(store.repo_dir(repo["id"]) / "map.json", {})
        if not m.get("concepts"):
            continue
        root = Path(repo["path"])
        ref = await asyncio.to_thread(default_ref, root)
        changes = await asyncio.to_thread(
            git, root, "log", "--since=7 days ago", "--format=%h %s", "--name-only", ref, "--"
        )
        items.append(
            {
                "repo": repo["id"],
                "name": repo["name"],
                "changes": changes[:12000],
                "map": m,
                "learner": Knowledge(store, repo["id"]).states(),
            }
        )
        roots.append(root)
    if not items:
        raise ValueError("Map at least one repository before generating a digest")
    job = home() / "digests" / time.strftime("%Y-%m-%d-%H%M%S")

    def validate(output):
        from .models import Digest

        value = Digest.model_validate(read_json(output / "digest.json", {})).model_dump()
        if (
            not isinstance(value.get("title"), str)
            or not isinstance(value.get("summary"), str)
            or not isinstance(value.get("repos"), list)
        ):
            raise ValueError("Digest needs title, summary and repos")
        by_id = {item["repo"]: item for item in items}
        for item in value["repos"]:
            if item.get("repo") not in by_id:
                raise ValueError("Unknown digest repository")
            known = {c["id"] for c in by_id[item["repo"]]["map"]["concepts"]}
            if any(c not in known for c in item.get("revisit", [])):
                raise ValueError("Unknown digest concept")
        return value

    result = await service.runner.run(
        "digest",
        roots[0],
        {"repos": items},
        job,
        store.profile()["model"],
        validate,
        lambda text: None,
        timeout=180,
        budget=1,
    )
    value = {
        **result["value"],
        "metrics": result["metrics"],
        "path": str(job / "output/digest.json"),
        "created_at": time.time(),
    }
    write_json(home() / "digest.json", value)
    return value
