# AGENTS.md

Instructions for coding agents other than Claude Code (for example OpenAI Codex).

The project rules live in one place, so they don't drift apart: **read `CLAUDE.md` first and follow it
exactly**. It applies to you too, not only to Claude. Then read `GOTCHA.md`.

The short version:

- `git fetch` and `git status -sb` before any work; pull `main` if it is behind.
- One branch per task (`t-NN-short-name`), and every change goes through a pull request.
- Before pushing, run `make test` and `ruff check .`.
- Never commit `.env` or put a secret in code. Never hand-edit `requirements.txt`.
- When reviewing a PR, report findings; don't push commits to someone else's branch unless asked.
