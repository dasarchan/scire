#!/bin/sh
# Scire installer for macOS and Linux. No sudo or provider credentials required.
set -eu
VERSION=${SCIRE_VERSION:-0.1.2}
OPENCODE_VERSION=1.18.35
RELEASE=https://github.com/dasarchan/scire/releases/download/v$VERSION
fail() { printf '\nScire: %s\n' "$*" >&2; exit 1; }
case "${1:-}" in
    --help) printf '%s\n' 'Install Scire, uv/Python, and OpenCode when needed.' 'Usage: sh install.sh [--help]' 'SCIRE_VERSION=0.1.2 selects a release.'; exit 0 ;;
    '') ;;
    *) fail "Unknown argument: $1 (try --help)" ;;
esac
case "$(uname -s)" in Darwin|Linux) ;; *) fail 'Supported systems: macOS and Linux.' ;; esac
# Reject malformed release names before constructing URLs.
case "$VERSION" in ''|*[!0-9.]*|.*|*..*|*.) fail 'SCIRE_VERSION must look like 0.1.2.' ;; esac
command -v curl >/dev/null 2>&1 || fail 'Install curl, then run this installer again.'
command -v git >/dev/null 2>&1 || fail 'Install Git first (macOS: xcode-select --install), then try again.'
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
fetch() { curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 --max-time 600 "$1" -o "$2"; }
# Resolve the release before making any installation changes.
WHEEL=scire_local-$VERSION-py3-none-any.whl
printf 'Downloading Scire %s…\n' "$VERSION"
fetch "$RELEASE/$WHEEL" "$TMP/$WHEEL"
fetch "$RELEASE/SHA256SUMS" "$TMP/SHA256SUMS"
EXPECTED=$(awk -v name="$WHEEL" '$2 == name {print $1}' "$TMP/SHA256SUMS")
[ "${#EXPECTED}" -eq 64 ] || fail 'Release checksum is missing.'
if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL=$(sha256sum "$TMP/$WHEEL" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then
    ACTUAL=$(shasum -a 256 "$TMP/$WHEEL" | awk '{print $1}')
else
    fail 'Install sha256sum or shasum to verify the download.'
fi
[ "$ACTUAL" = "$EXPECTED" ] || fail 'Release checksum does not match; nothing was installed.'
PATH="$HOME/.local/bin:$PATH"
export PATH
if ! command -v uv >/dev/null 2>&1; then
    printf 'Installing uv (and Python when needed)…\n'
    fetch https://astral.sh/uv/install.sh "$TMP/uv-install.sh"
    UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$TMP/uv-install.sh"
fi
# Keep an existing OpenCode 1 installation. A managed copy avoids replacing OpenCode 2.
OC=${SCIRE_OPENCODE:-}
[ -n "$OC" ] || OC=$(command -v opencode 2>/dev/null || true)
[ -n "$OC" ] || OC="$HOME/.opencode/bin/opencode"
OC_VERSION=$("$OC" --version 2>/dev/null || true)
case "$OC_VERSION" in
    1.*) printf 'Using OpenCode %s.\n' "$OC_VERSION" ;;
    *)
        printf 'Installing OpenCode %s for Scire…\n' "$OPENCODE_VERSION"
        fetch https://opencode.ai/install "$TMP/opencode-install.sh"
        mkdir -p "$TMP/opencode-home"
        HOME="$TMP/opencode-home" bash "$TMP/opencode-install.sh" --version "$OPENCODE_VERSION" --no-modify-path
        mkdir -p "$HOME/.local/share/scire/bin"
        cp "$TMP/opencode-home/.opencode/bin/opencode" "$HOME/.local/share/scire/bin/opencode"
        chmod 755 "$HOME/.local/share/scire/bin/opencode"
        ;;
esac
uv tool install --force --reinstall --python 3.11 "$TMP/$WHEEL"
BIN=$(uv tool dir --bin)
printf '\nScire is installed. Connect your repos and provider:\n  %s/scire setup\n\nThen launch:\n  %s/scire\n' "$BIN" "$BIN"
case ":${PATH}:" in
    *":$BIN:"*) ;;
    *) printf '\nTo use the short command, run: uv tool update-shell\nThen open a new terminal.\n' ;;
esac
