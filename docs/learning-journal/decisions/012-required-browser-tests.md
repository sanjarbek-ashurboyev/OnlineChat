# 012 · CI requires the browser tests; elsewhere they may skip

- **Date:** 2026-10-12 · **Status:** Accepted (session 025)

## Problem
Codex audit M-22: any error while starting the browser (`except Exception`) became a skip. A broken Playwright or
Chromium in CI would turn the browser tests into `skipped` and the job would still be green. The failed start also
left `DJANGO_ALLOW_ASYNC_UNSAFE=true` set for every later test.

## Options considered
1. **A switch, `REQUIRE_BROWSER_TESTS=True`, set in the CI job that runs them.** With it on, every reason to skip is
   an error. Without it, the tests skip and say why.
2. **Required whenever the database is Postgres.** No new variable, but anyone running the full suite against Docker
   without Chromium downloaded would get errors instead of skips.
3. **Count skips in CI** (fail the job if the runner reports skipped browser tests). Works from outside the tests,
   but needs parsing of the runner's output, which breaks when it changes.

## Chosen: option 1
- The place that must run them says so explicitly, in `.github/workflows/tests.yml`.
- `make test` on SQLite and a local run without Chromium behave as before.
- Even without the switch, only Playwright's "Executable doesn't exist" error may skip; any other launch error
  fails, because it means something is broken, not missing.

## Disadvantages and limits
- One more environment variable to know about. It's named in the workflow, the testing guide and GOTCHA.
- If someone adds a new CI job that runs the browser tests and forgets the switch, that job could skip them again.

## When another option is better
- **Option 3** if browser tests move to their own job or tool (e.g. pytest with `--strict` skip handling), where the
  runner can be told to treat skips as failures directly.
