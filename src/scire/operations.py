from __future__ import annotations
import re
import shutil
import subprocess
import sys
from .agent import opencode_binary
from .paths import home
from .store import Store

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
        checks.append((binary, shutil.which(binary) or "missing"))
    try:
        checks.append(("OpenCode", opencode_binary()))
    except ValueError:
        checks.append(("OpenCode", "missing — install https://opencode.ai"))
    checks.append(("Python", sys.version.split()[0]))
    checks.append(("State", str(home())))
    checks.append(("Model", Store().profile().get("model") or "not selected — scire setup --connect"))
    for name, value in checks:
        print(f"{name:12} {value}")
    return all(not value.startswith("missing") for _, value in checks)
