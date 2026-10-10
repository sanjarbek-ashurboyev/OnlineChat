# 005 · Setting up this learning journal

- **Date:** 2026-10-10 · **Phase:** Stage 0, documentation
- **Files:** `CLAUDE.md` (new), `docs/learning-journal/**` (new); `docs/journal.md` was created, then replaced
- **Objective:** a journal you can learn from months later, kept up to date as part of every task.

## What we accomplished
- **Added `CLAUDE.md`** at the project root:
  - the coding guidelines from
    [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills),
    copied unchanged after reading them (think before coding, simplicity, surgical changes, verify);
  - a project section with the stack, the branch and dependency rules, and the journal rule.
- **First attempt:** a single file, `docs/journal.md`, with a basics section and one entry per step.
- **Changed approach:** you then gave a detailed specification (sessions, concepts, decisions,
  problems, a progress and learning tracker). The single file was split into this structure, and
  `docs/journal.md` was removed so there's no duplicate.
- **Re-read the code** (`root/asgi.py`, `chats/consumers.py`, `chats/middleware.py`, `chats/views.py`,
  `accounts/*`, `assets/app.js`) so [project-overview.md](../project-overview.md) matches it.
- **Corrected two claims** while checking against the docs:
  - The scaling plan has no FastAPI decision record (that was discussed in chat only), so the
    decision index now lists the plan's real decisions.
  - The Channels guide now says the plan keeps one Django codebase, which is what `docs/scaling/README.md`
    states, instead of a conclusion the docs don't contain.
- **Learning baseline** recorded in [progress.md](../progress.md#learning-tracker). Everything is
  *Explained*; your level is *Unknown* until you do the exercises.

## Concepts I learned
- No new technical concept. The idea worth knowing: **documentation is part of the work**. An
  explanation written when the decision is made is far more accurate than one reconstructed later.
  Compare session 001 (written afterwards) with session 003.

## Problems we encountered
- None in the code. Process note: a Claude Code safety hook blocks shell commands containing
  `force`-style text, even inside file content, so some files were written with a different tool.
  This had no effect on the content.

## What I should remember
- Separate the **what** (sessions, progress) from the **why** (decisions) and the **how it works** (concepts).
- Mark uncertain things as uncertain (*Hypothesis*, *written afterwards*).

## Review questions
1. Where would you record "we chose Redis Streams over Postgres for X, because Y"?
2. Where would you record "the chat list was slow because of a missing index; here's how we found it"?
3. What has to happen before a concept moves from *Explained* to *Demonstrated* in the tracker?

<details><summary>Answer key</summary>

1. A new file in `decisions/`, linked from the session where it was decided.
2. `problems-and-solutions.md`, with a link from the session. If indexes are new to you, also add a concept guide.
3. You explain or apply it yourself without help. Accepting AI-written code doesn't count.
</details>

## Next steps
- Commit `CLAUDE.md` and `docs/learning-journal/` on `main`, and T-08 on its branch.
- Do the first exercises in [progress.md](../progress.md#learning-tracker), starting with
  watching WebSocket frames in DevTools.
- Then T-11 (tests and CI).
