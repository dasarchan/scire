from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_lock = threading.RLock()
_local = threading.local()
SECRET_NAME = re.compile(
    r"(^\.|^env\.storage\.|(?:^|[._-])(?:secrets?|credentials|tokens?)(?:[._-]|$)|\.(?:pem|key|p12|pfx)$)",
    re.I,
)
EXCLUDED = {"node_modules", "vendor", "dist", "build", "coverage", "__pycache__", "target", "venv"}


def home() -> Path:
    path = Path(os.environ.get("SCIRE_HOME", "~/.scire")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps(value, ensure_ascii=False, indent=2)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".scire-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def transaction():
    with _lock:
        if getattr(_local, "depth", 0):
            yield
            return
        lock = home() / "state.lock"
        with lock.open("a+") as stream:
            os.chmod(lock, 0o600)
            try:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                _local.depth = 1
                yield
            finally:
                _local.depth = 0
                try:
                    import fcntl

                    fcntl.flock(stream, fcntl.LOCK_UN)
                except ImportError:
                    pass


def repo_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]


def safe_source(root: Path, name: str) -> Path:
    if not name or "\\" in name or Path(name).is_absolute():
        raise ValueError("Use a repository-relative source path")
    parts = Path(name).parts
    if any(p in {"..", "."} or SECRET_NAME.search(p) or p in EXCLUDED for p in parts):
        raise ValueError("That source path is excluded")
    root = root.resolve()
    path = root.joinpath(*parts).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Source path escapes the repository")
    if path.stat().st_size > 512_000:
        raise ValueError("Source file exceeds 512 KB")
    data = path.read_bytes()
    if b"\0" in data:
        raise ValueError("Binary source is not supported")
    data.decode("utf-8")
    return path
