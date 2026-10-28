# Changelog

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
