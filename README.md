# Scire

Keep your understanding of a codebase current. Scire turns a repository or change into short, source-backed lessons, asks you to predict what the code does, and adapts the next round to your answers.

Python 3.11+ · local web app · headless OpenCode · no frontend build step

## Install

Install [uv](https://docs.astral.sh/uv/) and [OpenCode](https://opencode.ai/docs/). Scire is tested with OpenCode 1.18.35. Git is required; [GitHub CLI](https://cli.github.com/) is needed for GitHub PRs and posting comments.

```sh
uv tool install --python 3.11 git+https://github.com/dasarchan/scire.git@latest
scire
```

The repository is currently private, so Git access is required. If you use GitHub CLI authentication, run `gh auth setup-git` before the Git-based install. From a local checkout:

```sh
uv tool install --python 3.11 /path/to/scire
```

On first use, pick an existing OpenCode account or connect a provider, select `provider/model`, then choose repositories and describe your experience in the browser. To connect another account, run `scire setup --connect`. Login, browser OAuth and key entry happen inside OpenCode. Scire does not collect credentials in its web app. Provider and subscription access follow what OpenCode supports.

`scire init` is an alias for `scire setup`. A fast triage model can be selected in Settings; otherwise Scire uses your main model.

## Use

```sh
scire learn --repo ~/work/project
scire review 123 --repo ~/work/project
scire review https://github.com/owner/project/pull/123 --repo ~/work/project
scire review main...feature --repo ~/work/project
scire ask "How does a request reach its handler?" --repo ~/work/project
scire map --repo ~/work/project
scire prefetch
```

The browser is the main workspace. Choose skip, skim, standard or deep for each area before your first lesson. Read a module as soon as it arrives; OpenCode's public progress and elapsed time remain visible while the rest is generated. Click a source reference to pin the code pane, resize it, or step through an identifier's uses.

Every question has “I don’t know.” Feedback is immediate. Findings in a review unlock after you answer that module's questions. You can agree, be unsure or disagree and edit the draft. Posting requires a separate explicit action after an exact text and line preview. A moved PR head blocks posting from the old review. Local branch reviews keep drafts local.

Maps build automatically from the locally available default branch and refresh when that commit changes. Up to two maps run together. PR snapshots are pinned to their head commit; your checkout and its Git metadata are never changed. PR-only concepts stay hidden from default-branch knowledge views until their anchors appear there.

## Your data

**Data lives in `~/.scire/`.** This includes `repos.json`, your profile, learner evidence, per-repository maps, independent mirrors and worktrees, sessions, JSON agent output and run metrics. Source snapshots exclude dotfiles, generated directories and recognized secret files/content. Source viewing also blocks traversal and symlink escapes.

Scire binds one server to `127.0.0.1` with a random token stored in `server.json` with mode `0600`. A second command reuses it; a changed build restarts it. Ctrl-C stops a foreground server and its agents. Commands that need a server can start it in the background; `scire quit` stops it.

Source sent for inference goes to the provider selected in OpenCode. OpenCode retains its own account and session storage separately. Scire's learner history remains local.

## Maintenance

```sh
scire status
scire open
scire quit
scire doctor
scire --version
scire update
scire digest
scire digest --schedule       # macOS: Monday, 9:00 AM
scire install-skill           # ~/.claude/skills/scire/SKILL.md
```

The weekly digest is a CLI command, separate from the homepage. Scheduled output goes to `~/.scire/digest.log`; the LaunchAgent is `~/Library/LaunchAgents/ai.scire.digest.plist`. Remove the schedule with `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.scire.digest.plist`, then delete that plist.

The optional skill lets an existing coding agent launch Scire and carry the person's question into a session. It does not require Claude for inference: all teaching still uses OpenCode. `scire install-skill --path <folder>` supports another agent's skill directory.

`scire update` reads the uv installation receipt, checks numeric release tags and reinstalls from `latest`. Scire checks for updates in a background thread at most daily. Release CI advances `latest` after a release.

## How it works

1. A static skeleton extracts units, package imports, ranked definitions, entry points, documentation headings, hot files and Git co-change.
2. OpenCode writes a semantic map of areas and connected concepts. New agents receive the skeleton and relevant learner evidence.
3. Agents write per-module previews and JSON lessons. Pydantic schemas and literal, symbol or line anchors are checked; a non-unique literal needs an occurrence. Multi-line listings must match every source line. Invalid output gets at most two fix passes. Published modules stay immutable.
4. A Bayesian knowledge model accounts for guessing, slips, forgetting and changed code. Stable concept aliases retain evidence across map rebuilds. Answer orders are balanced and persisted in `orders.json`.

Runs have time and reported-cost limits; elapsed time, token counts, reported cost and fix passes are recorded. A provider can report $0 for subscription usage, so reported cost is not an independent billing estimate. Interrupted runs preserve validated modules and answers.

## Development

```sh
uv sync --group dev
uv run pytest
SCIRE_BROWSER=chromium uv run pytest       # after: uv run playwright install chromium
uv run ruff check src tests --select F,E9
uv run ruff format --check src tests
uv run scire
```

`SCIRE_BROWSER` may also be a Chrome executable path. Browser checks exercise the running app, including phone widths and review gates. Real provider measurements are in [docs/validation.md](docs/validation.md). Prompts live in `src/scire/prompts/`; HTML/CSS/JS are served directly from `src/scire/static/`.
