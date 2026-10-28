# Changelog

## v0.1.4 — 2026-10-27

- Replace the top-bar repository modal with an anchored dropdown, searchable repo list, selected checkmark and compact paths.
- Support keyboard navigation, outside-click dismissal and narrow screens.
- Keep repository selection on reload and when switching from a lesson back to the overview.

## v0.1.3 — 2026-10-27

- Add Scire to shell PATH configuration automatically and show short setup commands.
- Detect the caller's original PATH and explain how to enable Scire in the current terminal.
- Reuse the managed OpenCode installation when rerunning the installer.

## v0.1.2 — 2026-10-27

- Make Scire public and add a one-command macOS/Linux installer with verified release downloads.
- Bootstrap uv, Python and compatible OpenCode without sudo or replacing existing OpenCode installations.
- Publish release assets and checksums automatically; prepare optional PyPI Trusted Publishing.
- Support updates from wheel installations and make GitHub CLI optional in diagnostics.

## v0.1.1 — 2026-10-27

- Discover local Git repositories during terminal setup and select connections with a searchable checklist.
- Add keyboard folder browsing for repositories outside the initial search.
- Remove repository path entry from the web app; show terminal-selected connections and sync changes without losing profile edits.
- Keep learner history when disconnecting repositories and wait until profile setup finishes before starting automatic maps.

## v0.1.0 — 2026-10-27

- Introduce Scire: a Python CLI and local browser workspace for keeping codebase understanding current.
- Use headless OpenCode with the user's chosen provider and model; pass provider login through to native OpenCode setup.
- Add static repository skeletons, automatic semantic maps and a persistent learner model with forgetting and code-change discounts.
- Stream short anchored lessons, balance answer choices, provide immediate feedback and suggest what to learn next.
- Add pinned change reviews with gated findings, editable drafts, head-change checks and explicit GitHub comment previews.
- Add Ask triage, review prefetch, weekly digests, diagnostics, updates and an optional agent-launch skill.
- Keep Scire state under `~/.scire/` and all source checkouts read-only to teaching agents.
