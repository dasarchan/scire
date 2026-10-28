---
name: scire
description: Open Scire to learn a repository or understand a pull request with short lessons and adaptive questions. Use when the human asks to learn or refresh their understanding of code.
---

Run `scire doctor` if installation or provider access is uncertain. Scire uses the person's OpenCode provider login and stores learning history under `~/.scire/`.

From the requested repository, run `scire learn --repo <path>` for a new learning session, or `scire review <number|URL|branch|base..head> --repo <path>` for a pinned change review. These commands open a local browser workspace. Use `scire ask "<user's question>" --repo <path>` to carry the person's exact question into the session. Include relevant session context in that question when the user asks for it.

Scire handles teaching, anchored questions, and the persistent learner model. Let the human answer the questions. Proposed review comments remain drafts; posting requires the human's explicit action in Scire.
