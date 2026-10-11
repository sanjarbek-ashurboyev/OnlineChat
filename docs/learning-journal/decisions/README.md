# Decisions

Each file records one decision: the problem, the options, what we chose and why, and when we'd
choose differently. If new evidence changes a decision, update the file and say what changed.

| # | Decision | Status | Session |
|---|---|---|---|
| [001](001-settings-from-environment.md) | Settings and secrets come from environment variables | Accepted | [003](../sessions/003-t01-settings-from-environment.md) |
| [002](002-pinned-dependencies-with-pip-tools.md) | Pin all dependencies with pip-tools | Accepted | [004](../sessions/004-t08-pinned-dependencies.md) |
| [003](003-one-branch-per-task.md) | One git branch per backlog task, from `main` | Accepted | [002](../sessions/002-review-and-first-commit.md), [003](../sessions/003-t01-settings-from-environment.md) |
| [004](004-browser-tests-with-playwright.md) | Test the frontend with Playwright, in a real browser | Accepted | [016](../sessions/016-codex-review-frontend-fixes.md) |
| [005](005-client-ip-and-throttle-outages.md) | Which IP a throttle counts, and what it does when Redis is down | Accepted | [019](../sessions/019-account-security.md) |
| [006](006-socket-rights-end-with-the-token.md) | An open WebSocket's rights end with its token | Accepted | [020](../sessions/020-websocket-hardening.md) |

The bigger scaling decisions are in the plan, [docs/scaling/02-plan.md](../../scaling/02-plan.md):
- **Stage 0:** 0.1 where secrets live, 0.2 rate limiting, 0.3 making live delivery recoverable.
- **Stage 1:** 1.1 managed vs self-hosted Postgres, 1.2 connection pooling, 1.3 fewer calls per
  message, 1.4 the chat list query.
- **Stage 2:** 2.1 separate HTTP and WebSocket processes, 2.2 presence, 2.3 inbox data model,
  2.4 background jobs.

Read the matching plan decision before starting each task.
