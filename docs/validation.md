# v0.1.0 validation

Validated on macOS with Python 3.11.11, OpenCode 1.18.35, Chrome and the real `pallets/flask` repository at `d086db8`. Its static skeleton includes 206 files, 662 imports and 120 ranked definitions. Git co-change used the available shallow history.

| Operation | Result | Time | OpenCode reported cost | Fix passes |
| --- | --- | ---: | ---: | ---: |
| Semantic map | 7 areas, 25 connected concepts, 100% of files accounted for | 107.9s | $0.000 | 0 |
| Calibration | 3 streamed modules, 7 questions across 7 areas | 105.8s | $0.000 | 0 |
| Change review | 2 modules for Flask's MethodView query change (`2a8a38b~1..2a8a38b`) | 100.2s | $0.000 | 1 |
| Ask | Quick answer to “Where does Flask convert a view's dict return into JSON?” with validated references | 31.4s | $0.000 | 0 |
| Weekly digest | Validated repository changes and revisit concepts | 85.5s | $0.000 | 0 |

These runs used `openai/gpt-6.1-sol` through existing OpenCode OAuth. Reported cost is the provider's value, not an independent subscription billing estimate. Other providers and plans use native OpenCode login; they were not individually tested here.

A concurrent startup failed once before inference, so startup now retries twice and saves sanitized diagnostics if it still fails. The account rejected a catalog-listed mini model; the access error was surfaced and Ask was verified with the working model. A listed model must be accessible through the person's provider account.

The final suite has 24 passing checks, including a running Chrome app test. Automated checks cover strict anchors and listings, exclusions and traversal, map identities, Bayesian forgetting and changed-code discounts, streamed answer persistence, balanced stable answer orders, instant feedback, finding gates, exact comment previews, private patch filtering, source checkout protection, provider handoff, uv receipts, review ordering, single-server concurrency and agent process-group shutdown.

Chrome checks cover the actual Flask output, source pinning, keyboard resizing, code citations, completion and next steps, the Knowledge tree, desktop/narrow/phone widths and no horizontal page overflow. The automated running-app check also exercises inline Ask answers and their source preview. A real private GitHub PR was fetched into a separate pinned worktree using existing GitHub CLI authentication. No GitHub review comments were posted.

Weekly scheduling is checked through its generated LaunchAgent configuration; no recurring job was installed during development. GitHub posting is covered through gating and preview tests, without posting a comment to a real PR.


## v0.1.1 setup validation

The suite now has 39 passing checks, including two running Chrome tests. Repository setup covers search/Space/Enter keyboard selection, existing connections, cancellation, linked Git worktrees, exclusions and symlink handling, bounded scans, folder browsing, preserved learning history and live connection updates without losing profile edits.

A real home-folder scan found 76 repositories across 7,887 directories in 1.4 seconds. The interactive check also included the existing Flask connection outside the home folder: 77 repositories in 0.6 seconds on a warm scan. Depth-limited results are labelled and another folder can be searched through the terminal browser. No source contents were read for discovery, and no AI inference was started by the picker.

The real Flask connection appeared read-only in Settings. Chrome verified that setup has no repository path field, waits for a terminal selection, and submits no paths. Desktop and phone-width checks passed.

## Public distribution — v0.1.2 (2026-10-27)

- 45 pytest checks passed on macOS, including both running Chrome app tests, installer bootstrap and reuse, corrupt-download rejection before mutation, wheel receipt updates, and managed OpenCode selection.
- Installer tests use an isolated home (including spaces) and substitute only downloads/tool binaries; the actual `install.sh` runs under `/bin/sh`.
- Ruff correctness/format checks and wheel/sdist builds passed. PyPI publishing remains explicitly manual until a PyPI account owner registers the Trusted Publisher.

## Installer PATH fix — v0.1.3 (2026-10-27)

- 47 checks passed, including running Chrome app tests and real uv shell configuration tested by launching fresh bash and zsh shells.
- Regression coverage verifies that shell setup receives the caller's original PATH even after uv bootstrap, prints short commands, and reuses the managed OpenCode binary on a second install.
