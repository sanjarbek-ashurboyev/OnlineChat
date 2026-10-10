# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Project: OnlineChat

Source of the guidelines above: https://github.com/multica-ai/andrej-karpathy-skills (CLAUDE.md).

- Django + Channels chat app: REST API (DRF + SimpleJWT) and one WebSocket per user (`chats/consumers.py`), Redis for the channel layer, cache and presence, Postgres for data.
- The scaling plan and task backlog (T-01…T-37) live in `docs/scaling/`. Start from `docs/scaling/README.md`.
- Before any work: `git fetch` and check `git status -sb`. If `main` is behind `origin/main`, pull first.
- One branch per task, named `t-NN-short-name`, branched from an up-to-date `main`. Docs-only changes may go straight to `main`.
- Before pushing, run what CI runs: `make test` (Django's runner with `root/settings_test.py`) and `ruff check .`.
- `DJANGO_DEBUG` uses `True`/`False`, following the existing convention.
- Dependencies (once T-08 is merged): edit `requirements.in`, then regenerate with Python 3.13 using
  `pip-compile --strip-extras requirements.in`. Never hand-edit `requirements.txt`.
- Settings come from `.env` (see `.env.example`). Never commit `.env` or put a secret in code.

## Learning journal (required)

The owner of this project is a junior Python backend developer, learning WebSockets, security
and scaling through this project. The journal in `docs/learning-journal/` is part of the work,
not an extra. Start every task by reading `docs/learning-journal/progress.md`.

After each meaningful unit of work (feature, bug fix, security or performance change, new library,
tests, a failed approach worth learning from), before calling it done:

1. Add or extend a numbered session note in `docs/learning-journal/sessions/`, following the template
   of the existing ones: what was done (files, actual test results, what is NOT done), concepts,
   a code walkthrough of the important parts, problems, decisions, "what I should remember",
   3–7 review questions with the answers in a `<details>` block, and next steps.
2. New idea → add or extend a guide in `concepts/` (definition, why, how, example, our project,
   alternatives, common mistakes, when to use). Link it; don't duplicate it.
3. Real choice between options → `decisions/NNN-*.md`. Real problem → `problems-and-solutions.md`,
   with the root cause labelled Confirmed or Hypothesis.
4. Update `progress.md` (milestones, verified results, learning tracker) and, if the architecture
   changed, `project-overview.md`.

Rules: describe the real code with real paths and real results; never invent output; no secrets or
tokens in the journal. Write simply, define every term the first time, and use small examples.
Never mark a concept "Demonstrated" for the user. Only they can, by explaining or applying it without help.
