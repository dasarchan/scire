from __future__ import annotations
import asyncio
import json
import os
import secrets
import shutil
import signal
import time
from pathlib import Path
from typing import Callable
import httpx
import json5
from .paths import write_json
from .skeleton import source_files

PROMPTS = Path(__file__).parent / "prompts"


def opencode_binary() -> str:
    override = os.environ.get("SCIRE_OPENCODE")
    candidates = [
        override,
        str(Path.home() / ".local/share/scire/bin/opencode"),
        shutil.which("opencode"),
        str(Path.home() / ".opencode/bin/opencode"),
        str(Path.home() / ".local/bin/opencode"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise ValueError("OpenCode is not installed. Install it from https://opencode.ai, then run scire setup.")


def provider_config() -> dict:
    base = Path(
        os.environ.get(
            "OPENCODE_CONFIG_DIR",
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode",
        )
    )
    providers = {}
    for path in [base / "config.json", base / "opencode.json", base / "opencode.jsonc"]:
        if path.is_file():
            value = json5.loads(path.read_text())
            providers.update(value.get("provider", {}))
    if os.environ.get("OPENCODE_CONFIG_CONTENT"):
        providers.update(json5.loads(os.environ["OPENCODE_CONFIG_CONTENT"]).get("provider", {}))
    return providers


def snapshot(source: Path, dest: Path) -> tuple[list[str], int]:
    dest.mkdir(parents=True, exist_ok=True)
    files, total, omitted = [], 0, 0
    for name in source_files(source):
        original = source / name
        if original.is_symlink():
            omitted += 1
            continue
        data = original.read_bytes()
        if total + len(data) > 20_000_000 or b"\0" in data:
            omitted += 1
            continue
        import re

        if re.search(rb"-----BEGIN .*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}", data):
            omitted += 1
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o400)
        total += len(data)
        files.append(name)
    return files, omitted


class AgentRunner:
    """A bounded headless OpenCode operation. No source checkout is writable."""

    def __init__(self):
        self.processes: set[asyncio.subprocess.Process] = set()
        self.cancelled = False

    async def close(self):
        self.cancelled = True
        await asyncio.gather(*(self.stop(p) for p in list(self.processes)), return_exceptions=True)

    async def stop(self, process):
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def run(
        self,
        kind: str,
        source: Path,
        payload: dict,
        job_dir: Path,
        model: str,
        validate: Callable,
        progress: Callable,
        stream: Callable | None = None,
        timeout=300,
        budget=3.0,
    ) -> dict:
        if not model or "/" not in model:
            raise ValueError("Choose an OpenCode provider/model in setup before starting AI work")
        job_dir.mkdir(parents=True, exist_ok=True)
        output = job_dir / "output"
        output.mkdir(exist_ok=True)
        filtered = job_dir / "source"
        files, omitted = await asyncio.to_thread(snapshot, source, filtered)
        config_dir = job_dir / "config"
        config_dir.mkdir(exist_ok=True)

        def scoped(path):
            path = str(path.resolve()) + "/**"
            return {path: "allow", path.lstrip("/"): "allow"}

        permission = {
            "*": "deny",
            "read": {"*": "deny", **scoped(filtered), **scoped(output)},
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "edit": {"*": "deny", **scoped(output)},
            "external_directory": "deny",
        }
        config = {
            "provider": provider_config(),
            "model": model,
            "share": "disabled",
            "autoupdate": False,
            "plugin": [],
            "mcp": {},
            "lsp": False,
            "formatter": False,
            "permission": permission,
            "agent": {
                "scire": {
                    "mode": "primary",
                    "description": "Read-only code tutor with scoped JSON output",
                    "permission": permission,
                    "steps": 45,
                    "maxSteps": 45,
                }
            },
        }
        password = secrets.token_urlsafe(32)
        env = {
            **os.environ,
            "OPENCODE_CONFIG": "",
            "OPENCODE_CONFIG_CONTENT": json.dumps(config),
            "OPENCODE_CONFIG_DIR": str(config_dir),
            "XDG_CONFIG_HOME": str(config_dir),
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE": "true",
            "OPENCODE_SERVER_USERNAME": "scire",
            "OPENCODE_SERVER_PASSWORD": password,
        }
        started = time.monotonic()
        cost = 0.0
        tokens = 0
        passes = []
        result = {}
        errors = []
        deadline = asyncio.timeout(timeout)
        process = None
        watcher = None
        events = None
        stderr_task = None
        try:
            async with deadline:
                diagnostic = b""
                for startup_attempt in range(3):
                    progress(
                        "Starting OpenCode"
                        if startup_attempt == 0
                        else f"Retrying OpenCode startup · {startup_attempt}/2"
                    )
                    process = await asyncio.create_subprocess_exec(
                        opencode_binary(),
                        "serve",
                        "--pure",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        "0",
                        cwd=job_dir,
                        env=env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        start_new_session=True,
                    )
                    self.processes.add(process)

                    async def drain(proc):
                        nonlocal diagnostic
                        while chunk := await proc.stderr.read(2048):
                            diagnostic = (diagnostic + chunk)[-8192:]

                    stderr_task = asyncio.create_task(drain(process))

                    async def boot(proc):
                        import re

                        while line := await proc.stdout.readline():
                            if match := re.search(rb"http://127\.0\.0\.1:\d+", line):
                                return match[0].decode()
                        raise ValueError("OpenCode could not start")

                    try:
                        url = await asyncio.wait_for(boot(process), 20)
                        break
                    except (ValueError, asyncio.TimeoutError):
                        await self.stop(process)
                        self.processes.discard(process)
                        await asyncio.gather(stderr_task, return_exceptions=True)
                        if startup_attempt == 2:
                            import re

                            detail = diagnostic.decode(errors="replace")
                            for key, value in env.items():
                                if re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.I) and len(value) > 3:
                                    detail = detail.replace(value, "[redacted]")

                            def redact_config(value):
                                nonlocal detail
                                if isinstance(value, dict):
                                    for key, child in value.items():
                                        if (
                                            re.search(r"key|token|secret|password", key, re.I)
                                            and isinstance(child, str)
                                            and child
                                        ):
                                            detail = detail.replace(child, "[redacted]")
                                        else:
                                            redact_config(child)
                                elif isinstance(value, list):
                                    for child in value:
                                        redact_config(child)

                            redact_config(config)
                            detail = re.sub(r"[A-Za-z0-9_-]{24,}", "[redacted]", detail)[-1000:]
                            write_json(job_dir / "startup-error.json", {"detail": detail})
                            raise ValueError(
                                "OpenCode could not start after three attempts; run scire doctor. Sanitized diagnostics: "
                                + str(job_dir / "startup-error.json")
                            )
                        await asyncio.sleep(0.5 * (startup_attempt + 1))
                async with httpx.AsyncClient(base_url=url, auth=("scire", password), timeout=None) as client:
                    response = await client.post(
                        "/session", params={"directory": str(job_dir)}, json={"title": f"Scire · {kind}"}
                    )
                    response.raise_for_status()
                    sid = response.json()["id"]
                    seen = set()
                    tools = set()
                    roles = {}

                    async def listen():
                        nonlocal cost, tokens
                        try:
                            async with client.stream(
                                "GET", "/event", params={"directory": str(job_dir)}
                            ) as feed:
                                async for line in feed.aiter_lines():
                                    if not line.startswith("data:"):
                                        continue
                                    e = json.loads(line[5:])
                                    p = e.get("properties", {})
                                    if p.get("sessionID") not in (None, sid):
                                        continue
                                    info = p.get("info", {})
                                    if e["type"] == "message.updated":
                                        roles[info.get("id")] = info.get("role")
                                        if (
                                            info.get("role") == "assistant"
                                            and info.get("time", {}).get("completed")
                                            and info["id"] not in seen
                                        ):
                                            seen.add(info["id"])
                                            cost += info.get("cost", 0)
                                            u = info.get("tokens", {})
                                            tokens += u.get("input", 0) + u.get("output", 0)
                                            if cost > budget:
                                                await self.stop(process)
                                    part = p.get("part", {})
                                    if part.get("type") == "tool" and part.get("id") not in tools:
                                        tools.add(part.get("id"))
                                        progress("Inspecting source · " + part.get("tool", "tool"))
                                        if len(tools) > 65:
                                            await self.stop(process)
                                    if (
                                        part.get("type") == "text"
                                        and roles.get(part.get("messageID")) == "assistant"
                                        and part.get("time", {}).get("end")
                                    ):
                                        text = part.get("text", "").strip()
                                        if text and not text.startswith(("{", "[", "```")):
                                            progress(text[:350])
                        except (httpx.HTTPError, asyncio.CancelledError, ValueError):
                            pass

                    async def watch():
                        while True:
                            if stream:
                                try:
                                    stream(output)
                                except (ValueError, OSError, json.JSONDecodeError):
                                    pass
                            await asyncio.sleep(0.2)

                    events = asyncio.create_task(listen())
                    watcher = asyncio.create_task(watch())
                    context = {
                        **payload,
                        "source_root": str(filtered),
                        "output_root": str(output),
                        "readable_files": files,
                        "omitted_files": omitted,
                    }
                    schema = (PROMPTS / "schema.md").read_text()
                    prompt = (
                        (PROMPTS / "system.md").read_text()
                        + "\n"
                        + (PROMPTS / f"{kind}.md").read_text()
                        + "\n"
                        + schema
                        + "\nINPUT DATA:\n"
                        + json.dumps(context, ensure_ascii=False)
                    )
                    provider, model_id = model.split("/", 1)
                    for attempt in range(3):
                        pass_started = time.monotonic()
                        before = cost
                        text = (
                            prompt
                            if attempt == 0
                            else (PROMPTS / "fix.md").read_text()
                            + "\nValidation failures:\n"
                            + json.dumps(errors)
                            + "\nOutput directory: "
                            + str(output)
                            + "\nKeep already published modules unchanged."
                        )
                        progress(
                            "Exploring source and writing modules"
                            if attempt == 0
                            else f"Fixing validation issues · pass {attempt}/2"
                        )
                        response = await client.post(
                            f"/session/{sid}/message",
                            params={"directory": str(job_dir)},
                            json={
                                "agent": "scire",
                                "model": {"providerID": provider, "modelID": model_id},
                                "parts": [{"type": "text", "text": text}],
                            },
                        )
                        response.raise_for_status()
                        data = response.json()
                        info = data.get("info", {})
                        if info.get("error"):
                            error = info["error"]
                            code = error.get("data", {}).get("statusCode", "")
                            raise ValueError(
                                f"OpenCode inference failed ({error.get('name', 'error')} {code}). Check provider login and model access."
                            )
                        if info.get("id") not in seen:
                            cost += info.get("cost", 0)
                            u = info.get("tokens", {})
                            tokens += u.get("input", 0) + u.get("output", 0)
                            seen.add(info.get("id"))
                        passes.append(
                            {
                                "pass": attempt,
                                "seconds": round(time.monotonic() - pass_started, 3),
                                "cost": round(cost - before, 6),
                            }
                        )
                        try:
                            result = validate(output)
                            if stream:
                                stream(output)
                            errors = []
                            break
                        except (ValueError, OSError, json.JSONDecodeError) as exc:
                            errors = [str(exc)[:4000]]
                            if attempt == 2:
                                raise ValueError(
                                    "Agent output failed validation after two fix passes: " + errors[0]
                                ) from exc
                        if cost >= budget:
                            raise ValueError("Reported cost budget reached before the fix pass")
        except TimeoutError as exc:
            raise ValueError(
                f"OpenCode run timed out after {timeout} seconds; partial validated modules are preserved."
            ) from exc
        except httpx.HTTPError as exc:
            raise ValueError(
                "OpenCode connection failed or the operation budget was reached. Check activity and run metrics."
            ) from exc
        finally:
            for task in (watcher, events, stderr_task):
                if task:
                    task.cancel()
            await asyncio.gather(*(t for t in (watcher, events, stderr_task) if t), return_exceptions=True)
            if process:
                await self.stop(process)
                self.processes.discard(process)
            metrics = {
                "kind": kind,
                "model": model,
                "seconds": round(time.monotonic() - started, 3),
                "cost": round(cost, 6),
                "tokens": tokens,
                "passes": passes,
                "errors": errors,
                "started_at": time.time() - (time.monotonic() - started),
            }
            write_json(job_dir / "metrics.json", metrics)
        return {"value": result, "metrics": metrics}
