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
| [007](007-lost-echo-check-the-history.md) | When a message's echo doesn't come, check the history | Accepted | [021](../sessions/021-frontend-session-lifecycle.md) |
| [008](008-read-up-to-boundary.md) | Read receipts carry a read-up-to boundary | Accepted | [022](../sessions/022-message-receipts.md) |
| [009](009-cursor-pagination-for-history.md) | Message history pages by cursor | Accepted | [023](../sessions/023-message-ordering.md) |
| [010](010-blocked-peer-in-the-chat-list.md) | Someone who blocked you: keep the chat, blank their details | Accepted | [024](../sessions/024-privacy-and-uploads.md) |
| [011](011-delete-avatar-files-after-commit.md) | Delete old avatar files with our own signals, after the commit | Accepted | [024](../sessions/024-privacy-and-uploads.md) |
| [012](012-required-browser-tests.md) | CI requires the browser tests; elsewhere they may skip | Accepted | [025](../sessions/025-api-contract-and-browser-skips.md) |
| [013](013-start-a-chat-by-phone-number.md) | A chat starts from a phone number, not a user id | Accepted | [029](../sessions/029-t05-chat-by-phone.md) |
| [014](014-refresh-rotation-and-logout.md) | Refresh tokens rotate; logout blacklists; tabs share renewals | Accepted; blacklist replaced by 016 | [030](../sessions/030-t07-refresh-rotation-and-logout.md) |
| [015](015-check-pooled-connections.md) | Check each pooled connection; on a dead one, check them all | Accepted | [035](../sessions/035-dead-pooled-connections.md) |
| [016](016-login-sessions.md) | A row per login: single-use refresh tokens and logout by session | Accepted | [036](../sessions/036-login-sessions.md) |

The bigger scaling decisions are in the plan, [docs/scaling/02-plan.md](../../scaling/02-plan.md):
- **Stage 0:** 0.1 where secrets live, 0.2 rate limiting, 0.3 making live delivery recoverable.
- **Stage 1:** 1.1 managed vs self-hosted Postgres, 1.2 connection pooling, 1.3 fewer calls per
  message, 1.4 the chat list query.
- **Stage 2:** 2.1 separate HTTP and WebSocket processes, 2.2 presence, 2.3 inbox data model,
  2.4 background jobs.

Read the matching plan decision before starting each task.
