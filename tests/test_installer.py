"""Exercise the real shell installer without mutating the host's tools or accounts."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from scire import __version__

INSTALLER = Path(__file__).parents[1] / "install.sh"


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


@pytest.mark.parametrize("bootstrap", [False, True])
def test_installer_checks_download_and_keeps_login_separate(tmp_path, bootstrap):
    home = tmp_path / "home with spaces"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    uv = """#!/bin/sh
case "$1 $2" in
    'tool dir') echo "$HOME/.local/bin" ;;
    'tool update-shell')
        printf '%s\\n' "update-shell PATH=$PATH" >> "$CALLS"
        printf 'export PATH="%s/.local/bin:$PATH"\\n' "$HOME" > "$HOME/.zshenv"
        ;;
    *) printf '%s\\n' "$*" >> "$CALLS"; test -f "$7" ;;
esac
"""
    executable(bin_dir / "git", "#!/bin/sh\nexit 0\n")
    if not bootstrap:
        executable(bin_dir / "uv", uv)
    executable(bin_dir / "opencode", '#!/bin/sh\necho "${OC_VERSION:-1.18.35}"\n')
    executable(
        bin_dir / "curl",
        f"#!{sys.executable}\n"
        + """import os, sys, hashlib
from pathlib import Path
args=sys.argv[1:]
url=args[args.index('-o')-1]
out=Path(args[args.index('-o')+1])
if url.endswith('.whl'):
    out.write_bytes(b'release wheel')
elif url.endswith('SHA256SUMS'):
    digest=hashlib.sha256(b'release wheel').hexdigest() if not os.environ.get('CORRUPT') else '0'*64
    out.write_text(digest+'  scire_local-'+os.environ['SCIRE_VERSION']+'-py3-none-any.whl\\n')
elif url == 'https://astral.sh/uv/install.sh':
    out.write_text('mkdir -p "$UV_INSTALL_DIR"\\ncp "$MOCK_UV" "$UV_INSTALL_DIR/uv"\\n')
elif url == 'https://opencode.ai/install':
    out.write_text('mkdir -p "$HOME/.opencode/bin"\\nprintf "#!/bin/sh\\\\necho 1.18.35\\\\n" > "$HOME/.opencode/bin/opencode"\\n')
else:
    raise RuntimeError(url)
""",
    )
    uv_template = tmp_path / "uv-template"
    executable(uv_template, uv)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(bin_dir) + ":/usr/bin:/bin",
        "CALLS": str(log),
        "SHELL": "/bin/zsh",
        "SCIRE_VERSION": __version__,
        "MOCK_UV": str(uv_template),
        "OC_VERSION": "2.0.0" if bootstrap else "1.18.35",
    }
    env.pop("SCIRE_OPENCODE", None)
    # A failed integrity check must leave every tool untouched.
    result = subprocess.run(
        ["sh", str(INSTALLER)], env={**env, "CORRUPT": "1"}, capture_output=True, text=True
    )
    assert result.returncode and "checksum does not match" in result.stderr
    assert not log.exists()
    assert not (home / ".local").exists()
    result = subprocess.run(["sh", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tool install --force --reinstall --python 3.11" in log.read_text()
    assert "auth" not in log.read_text() and "setup" not in log.read_text()
    assert "  scire setup" in result.stdout
    assert "Open a new terminal" in result.stdout
    assert "export PATH='" + str(home / ".local/bin") + "':$PATH" in result.stdout
    assert (home / ".zshenv").exists()
    assert "update-shell PATH=" + env["PATH"] in log.read_text()
    assert "export PATH" in (home / ".zshenv").read_text()
    managed = home / ".local/share/scire/bin/opencode"
    assert managed.exists() == bootstrap
    if bootstrap:
        assert os.access(managed, os.X_OK)
        assert (home / ".local/bin/uv").exists()
    if bootstrap:
        # A second install must reuse Scire's managed binary.
        result = subprocess.run(["sh", str(INSTALLER)], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Installing OpenCode" not in result.stdout
    assert (bin_dir / "opencode").read_text().endswith('echo "${OC_VERSION:-1.18.35}"\n')


def test_installer_rejects_bad_version_before_network():
    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env={**os.environ, "SCIRE_VERSION": "../../other"},
        capture_output=True,
        text=True,
    )
    assert result.returncode and "SCIRE_VERSION" in result.stderr


def test_release_installer_version_matches_package():
    from scire import __version__

    assert "VERSION=${SCIRE_VERSION:-" + __version__ + "}" in INSTALLER.read_text()


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_real_uv_path_configuration_reaches_a_new_shell(tmp_path, shell):
    import shutil

    uv = shutil.which("uv")
    binary = shutil.which(shell)
    if not uv or not binary:
        pytest.skip("uv and shell required")
    home = tmp_path / "home with spaces"
    home.mkdir()
    target = home / ".local/bin/scire"
    target.parent.mkdir(parents=True)
    executable(target, "#!/bin/sh\necho installed\n")
    env = {
        "HOME": str(home),
        "SHELL": binary,
        "PATH": "/usr/bin:/bin",
        "UV_TOOL_BIN_DIR": str(target.parent),
    }
    result = subprocess.run([uv, "tool", "update-shell"], env=env, cwd=home, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [binary, "-lic", "command -v scire"], env=env, cwd=home, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert str(target) in result.stdout
