# Progress

*Updated: 2026-10-10 (session 005).*

**Status words:** **Done** = code written, tests or checks run and passing, committed.
**Partial** = some of the acceptance criteria are met. **Blocked** = waiting on something outside
our control. **Planned** = not started. Code that's written but not verified is never "Done".

## Current phase

**Stage 0: critical security and correctness fixes**, from
[docs/scaling/02-plan.md](../scaling/02-plan.md). The suggested order is in
[docs/scaling/README.md](../scaling/README.md#start-here-this-week):
T-01 → T-08 → T-11 → T-02/T-03/T-04 → T-09 → baseline load test.

## Milestones

| Milestone | Status | Evidence | Where |
|---|---|---|---|
| Audit, load test tooling, scaling plan | **Done** | Load test ran: 100 online healthy, 200 failed | `main` `4de99ca` |
| T-01 Settings from env, new secret key | **Done on branch**, not merged | 3/3 tests pass; `check --deploy` security warnings cleared; missing key fails loudly | `t-01-settings-from-env` `68468d0`. The rebased commit's push to GitHub isn't confirmed. |
| T-08 Complete, pinned dependencies | **Partial** | Fresh venv installs and passes checks; `pip-audit` clean | Uncommitted on `t-08-pinned-deps`. The `pip-audit`-in-CI step waits for T-11. |
| Learning journal | **Partial** | This structure created | Uncommitted, currently in the `t-08-pinned-deps` working tree |
| Point `origin` at the moved repository | **Blocked** (needs you) | Claude Code's auto mode refused to change the remote | Run `git remote set-url origin https://github.com/sanjarbek-ashurboyev/OnlineChat.git` |
| T-11 Tests + CI | Planned | | |
| T-02, T-03, T-04 | Planned | | |
| T-09 Gap fetch + reconnect jitter | Planned | | |
| Baseline load test (realistic profile, second machine) | Planned | | |

## Verified so far

| What | How | Result |
|---|---|---|
| Django config is valid | `manage.py check` | No issues (main, T-01, T-08) |
| No model changes missing a migration | `makemigrations --check --dry-run` | No changes |
| Tokens signed with another key are rejected | `accounts/tests.py` (T-01 branch) | Pass |
| Production settings | `check --deploy` with production env vars | Only W005/W021 (deliberate) and drf-spectacular schema warnings remain |
| Fresh install works | New venv + `pip install -r requirements.txt` | Imports OK, ASGI app loads, uses psycopg 3 |
| No known vulnerable versions | `pip-audit -r requirements.txt` | None found (2026-10-10) |

## Known issues (open)

See the [audit](../scaling/01-audit.md) for details. The most important still-open items:
- **SEC-3/4/5:** no rate limits on login, registration, messages or user lookup by id (T-03, T-04).
- **COR-1:** messages that arrive during a reconnect never show in the open chat (T-09).
- **COR-2:** a failed `group_discard` skips "mark offline" (T-02).
- **PERF-1/2/3:** one DB thread per process, plus a new DB connection per call (Stage 1).
- **OPS-1/2:** no tests on `main`, no CI (T-11).
- Your local `.venv` still has `psycopg2-binary`, `django-filter`, `Markdown` and psycopg 3.3.5.
  Sync it with `pip install -r requirements.txt` and uninstall those three.

## Documentation backlog

- None outstanding. Session 001 was written after the fact from the scaling docs and the
  previous session's summary, because the journal didn't exist yet. Treat its details
  as less certain than the later sessions.

---

## Learning tracker

**Levels:** Introduced → Explained → Practiced → Demonstrated (definitions in the
[README](README.md#how-to-use-it-to-learn)). **Unknown** = no evidence either way.

**Baseline (2026-10-10):** you described yourself as a junior Python backend developer who
knows Python and basic Django, and the basics of WebSockets and scaling, but not this level.
That's self-reported; nothing has been tested yet, so every concept starts at
*Explained* with your own level *Unknown*.

| Concept | Guide | Status | Evidence | Exercise to reach "Practiced" |
|---|---|---|---|---|
| HTTP vs WebSocket | [guide](concepts/http-and-websockets.md) | Explained | Sessions 001, 005 | Open the app, then the browser DevTools → Network → WS. Watch frames as you send a message. Write down every frame type you see. |
| Channels, consumers, groups, Redis channel layer | [guide](concepts/django-channels-and-redis.md) | Explained | Session 001 | Without looking, draw the path of one message from browser A to browser B, naming the functions in `chats/consumers.py`. |
| JWT and signing | [guide](concepts/authentication-and-jwt.md) | Explained | Session 003 | Paste an access token into a JWT decoder (offline tool or `python -c`). Explain each claim. Then change one character of the signature and explain why the server rejects it. |
| Configuration, secrets, DEBUG, HTTPS settings | [guide](concepts/configuration-and-secrets.md) | Explained | Session 003 | Start the server with `DJANGO_DEBUG=0` and no `DJANGO_ALLOWED_HOSTS`. Predict the error first, then check. |
| Dependency management | [guide](concepts/dependency-management.md) | Explained | Session 004 | Add a package to `requirements.in`, run `pip-compile`, and read the diff. Revert afterwards. |
| Git branches, merge, rebase | [guide](concepts/git-branches-merge-rebase.md) | Explained | Sessions 002, 003 | In a throwaway repo, make a fast-forward merge, a rebase and a `--force-with-lease` push to a local bare remote. |
| Performance, bottlenecks, load testing | [guide](concepts/performance-and-load-testing.md) | Explained | Session 001 | Recompute the PERF-4 table yourself for 150 users. Predict healthy or failing. |

Mark a row *Practiced* yourself after doing its exercise. It becomes *Demonstrated* when you
explain or apply the concept without help, for example by answering a session's review
questions out loud or fixing a related bug yourself.
