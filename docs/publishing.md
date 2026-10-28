# Publishing Scire

The public GitHub installer is the supported distribution channel. Package name: `scire-local`; executable: `scire`.

## GitHub releases

1. Bump `pyproject.toml`, `src/scire/__init__.py`, and the default `VERSION` in `install.sh`. Update the changelog and lockfile (`uv lock`).
2. Run the checks, commit, and push. Tag that commit `vX.Y.Z` and publish a GitHub release for the tag.
3. The release workflow tests, builds the wheel/source archive, uploads them with `install.sh` and `SHA256SUMS`, and advances `latest` only after the assets are uploaded.
4. Verify a fresh install using the README command. The public default branch is `latest`; stacked development PRs retain their original bases.

The installer selects a numbered release and verifies its wheel checksum. `SCIRE_VERSION=X.Y.Z` selects an older release. It never requests an inference key; run `scire setup` for native OpenCode login.

## Optional PyPI Trusted Publishing

PyPI requires a one-time action by the owner of a PyPI account; GitHub login alone cannot authorize it. No PyPI token is stored here.

1. Sign in to PyPI and add a pending publisher at https://pypi.org/manage/account/publishing/ with project **scire-local**, GitHub owner **dasarchan**, repository **scire**, workflow **publish-pypi.yml**, and environment **pypi**. If the project name is taken, change the package name and installer filenames before publishing.
2. Create the GitHub environment `pypi`; optionally require reviewer approval there.
3. Run **Publish to PyPI** from Actions, passing an existing release tag such as `v0.1.2`. The workflow builds that tag and publishes using GitHub's short-lived OIDC identity.
4. Once the first publish succeeds, advertise `uv tool install scire-local`. Keep the GitHub installer for people without Python or uv.

Official instructions: https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/

## Homebrew

A Homebrew tap can follow when there is demand. The GitHub installer already handles the Python and OpenCode prerequisites on macOS without adding a tap or requiring Homebrew. No `brew install scire` command is advertised until a formula exists and is tested.
