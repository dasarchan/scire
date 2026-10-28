import hashlib
from pathlib import Path
from . import __version__


def build_id():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".html", ".css", ".js", ".md"}:
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return __version__ + "-" + digest.hexdigest()[:12]
