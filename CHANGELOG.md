# Changelog

## v0.1.0 — 2026-10-27

- Introduce Scire: a Python CLI and local browser workspace for keeping codebase understanding current.
- Use headless OpenCode with the user's chosen provider and model; pass provider login through to native OpenCode setup.
- Add static repository skeletons, automatic semantic maps and a persistent learner model with forgetting and code-change discounts.
- Stream short anchored lessons, balance answer choices, provide immediate feedback and suggest what to learn next.
- Add pinned change reviews with gated findings, editable drafts, head-change checks and explicit GitHub comment previews.
- Add Ask triage, review prefetch, weekly digests, diagnostics, updates and an optional agent-launch skill.
- Keep Scire state under `~/.scire/` and all source checkouts read-only to teaching agents.
