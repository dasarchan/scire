# Changelog

## v0.1.8 — 2026-10-28

- Read lessons as one continuous page with interspersed questions and contextual source references.
- Choose a 2-, 5- or 10-minute budget; constrain explanations, questions and feedback, and use shorter targeted prompts.
- Rebuild Bayesian mastery from answer events with per-choice likelihoods, forgetting, code drift, area rollups and compact prompt summaries.
- Give every repo a home with mastery and session cards, a concept-tree modal, optional calibration and a PR/branch review table.
- Add pinned Changes views with diff hunks and old/new line numbers; remove the browser Ask box.
- Reopen connected workspaces with plain scire; reserve the repository picker for explicit setup after first use.

## v0.1.7 — 2026-10-28

- Fix OpenCode output permissions using job-relative paths and an isolated Git root; support GPT providers’ apply_patch tool in lesson instructions.
- Replace missing-manifest schema errors with a concrete file-writing error and repair instructions.
- Show mapping in a focused activity screen with streamed narration, tool titles, elapsed time, quiet-period status and completion/error states.
- Keep the transcript available after mapping, let users return to the workspace, and preserve scroll position while reading earlier output.

## v0.1.6 — 2026-10-28

- Introduce four-step, keyboard-friendly onboarding with optional background, back navigation, refresh recovery and inline save errors.
- Reuse the configured OpenCode model, keep advanced settings out of onboarding, and sync terminal-selected repos live.
- Refine app spacing, icons, typography, cards, buttons, lessons and source-view surfaces with one consistent dark theme.
- Avoid flashing the full workspace before the first setup question loads.

## v0.1.5 — 2026-10-28

- Simplify typography, remove decorative captions and slogans, and organize setup/settings into clear form sections.
- Replace browser model text fields and datalists with provider/model selects, custom-ID entry, and catalog loading/error/retry states.
- Preserve model selections across settings edits and let quick answers fall back to the teaching model.
- Replace terminal model dumps with searchable provider and model choosers.

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
