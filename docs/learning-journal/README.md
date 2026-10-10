# Learning journal

This journal records what we build in OnlineChat, **how it works and why it was done that
way**, so you can come back weeks later and understand it without the original chat.
It follows the real repository: file names, commands and results are the actual ones.

## How it's organized

| Document | What's in it | When to read it |
|---|---|---|
| [project-overview.md](project-overview.md) | What the app does, its architecture, every component and how they talk | First, and whenever you forget how a piece fits |
| [progress.md](progress.md) | What's done, in progress, blocked or planned. **Your learning tracker.** | At the start of each work session |
| [concepts/](concepts/README.md) | One guide per idea (WebSockets, JWT, env config…), from simple to advanced | When a session mentions an idea you can't explain yet |
| [decisions/](decisions/README.md) | Why we chose X over Y, with the trade-offs | Before changing something a decision covers; before interviews |
| [problems-and-solutions.md](problems-and-solutions.md) | Every real problem we hit, its root cause, how we diagnosed and fixed it | When something similar breaks |
| [sessions/](sessions/) | One numbered note per work session: what we did, learned, left open | Chronologically, to relive the project |

### Sessions so far

1. [001 · Project analysis and load test](sessions/001-project-analysis-and-load-test.md)
2. [002 · Review, first commit and push](sessions/002-review-and-first-commit.md)
3. [003 · T-01: secret key and settings from the environment](sessions/003-t01-settings-from-environment.md)
4. [004 · T-08: complete, pinned dependencies](sessions/004-t08-pinned-dependencies.md)
5. [005 · Setting up this learning journal](sessions/005-learning-journal-setup.md)
6. [006 · Syncing with GitHub, and redoing T-01 and T-08](sessions/006-syncing-with-github.md)
7. [007 · T-11: tests and CI against real services, secret scanning, branch protection](sessions/007-t11-tests-and-ci.md)

## How to use it to learn

1. **Read in this order the first time:** project overview → concepts in the order listed in
   [concepts/README.md](concepts/README.md) → sessions 001 onwards.
2. **Answer the review questions before opening the answers.** Every session ends with them.
   If you can't answer one, go back to the linked concept guide, not the answer key.
3. **Do the exercises** in [progress.md](progress.md#learning-tracker). Only after doing one
   should a concept move from *Explained* to *Practiced*. *Demonstrated* means you did it
   yourself without help: explained it out loud, wrote the code, or found a bug.
4. **Before a technical interview**, re-read [decisions/](decisions/README.md) and the
   "What I should remember" lists in each session. Interviewers ask "why", not "what".

## Related documentation

- [`docs/scaling/`](../scaling/README.md): the audit, the scaling plan and the task backlog
  (T-01…T-37). The journal explains the ideas; the scaling docs are the plan and the evidence.
- [`CLAUDE.md`](../../CLAUDE.md): instructions Claude Code reads every session, including the
  rule to keep this journal updated.
