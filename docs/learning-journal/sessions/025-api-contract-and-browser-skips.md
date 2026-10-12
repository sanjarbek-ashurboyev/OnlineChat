# 025 · Codex audit: an honest API schema, and browser tests that can't silently skip

- **Date:** 2026-10-12 · **Phase:** Stage 0
- **Task:** findings M-20 and M-22 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-api-contract-and-browser-skips`, stacked on `fix-privacy-and-uploads` (PR #34), so merge #34 first
- **Files:** `accounts/authentication.py`, `accounts/serializers.py`, `chats/serializers.py`, `chats/views.py`,
  `root/settings.py`, `chats/test_browser.py`, `.github/workflows/tests.yml`, `root/test_schema.py` (new),
  `chats/test_browser_setup.py` (new), docs
- **Objective:** the OpenAPI schema describes what the server really does, and a green CI run means the browser
  tests really ran.

## Before we started
- PR #34 (session 024) was still open, and this work edits the same journal files, so the branch is stacked on it.
- The schema generator printed **13 warnings (10 unique)**: 7 × "could not resolve authenticator
  `LastSeenJWTAuthentication`", 3 × "unable to resolve type hint" (`get_participant`, `get_last_message`,
  `get_is_online`). Reading the generated file turned up three more mismatches that print no warning: `POST /chats/`
  claimed to return `ChatCreate`, history claimed numbered pages with `count`, and an avatar upload was described as
  a URL string.
- Docker Desktop had stopped overnight; the first Postgres run got "connection refused". Started it with
  `open -a Docker`.

## What we accomplished
1. **Tests first.**
   - `root/test_schema.py`, 8 tests, all 8 failing on the old code: the schema has warnings; no endpoint declares a
     token (`'jwtAuth' not found in {}`); `participant` and `last_message` are strings; `is_online` is
     `'string' != 'boolean'`; `POST /chats/` returns `ChatCreate`; the read response has no body; history has
     `count`; the uploaded avatar is `'uri' != 'binary'`.
   - `chats/test_browser_setup.py`, 6 tests on a fake server and a fake Playwright, so they run on SQLite too. On the
     old code (with `REQUIRED` patched in) 5 failed, matching the audit: an unexpected launch error became a skip
     (`(0, 1) != (1, 0)`), and the environment kept `DJANGO_ALLOW_ASYNC_UNSAFE='true'`. The sixth, "locally, a
     missing Chromium is a skip", is a guard that passed before and still does.
2. **M-20, the schema:**
   - `LastSeenJWTScheme(SimpleJWTScheme)` with `target_class = LastSeenJWTAuthentication`: every endpoint now declares
     `jwtAuth` (Bearer JWT), except login and refresh (no auth) and registration (token optional).
   - `get_is_online(...) -> bool`; `@extend_schema_field(PublicUserSerializer)` on `get_participant`;
     `@extend_schema_field(inline_serializer('LastMessage', allow_null=True, ...))` on `get_last_message`.
   - `POST /chats/`: `@extend_schema_view(post=extend_schema(request=ChatCreateSerializer, responses={201: ChatSerializer}))`.
   - Read: `responses={200: inline_serializer('MarkReadResponse', fields={'marked_read': IntegerField()})}`.
   - History: `pagination_class = HistoryPagination` on the view, and the `paginator` property builds it from there.
     The `after` parameter's description says that catch-up pages by number and includes `count`.
   - `COMPONENT_SPLIT_REQUEST: True`: request and response schemas are separate.
3. **M-22, the browser tests:**
   - `REQUIRE_BROWSER_TESTS=True` (set in the `test-postgres-redis` job) turns every reason to skip into an error
     ([decision 012](../decisions/012-required-browser-tests.md)).
   - Without it, only Playwright's "Executable doesn't exist" error may skip; any other launch error fails.
   - Every setup step's undo is registered with `cls.addClassCleanup` before the step runs; if anything fails after
     the live server started, `setUpClass` stops the server itself. The `tearDownClass` override is gone.
4. **Checked for real, not only with fakes:**
   - SQLite settings with the switch on: 8 errors, "REQUIRE_BROWSER_TESTS is True, but the browser tests can't run:
     needs Postgres and Redis".
   - Postgres with Chromium hidden (`PLAYWRIGHT_BROWSERS_PATH` pointing at an empty folder): with the switch,
     `ERROR: setUpClass` with Playwright's error; without it, `OK (skipped=1)`.
5. **Results:** `make test` → **146 run, OK (12 skipped)**. Real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True` →
   **171 tests, OK** (browser tests included, nothing skipped). `ruff check .` clean. `makemigrations --check`: no
   changes. `spectacular --validate`: **0 warnings, 0 errors** (was 13 warnings).

**Not done:**
- **Error responses aren't described** (400, 401, 404, 429). The schema lists only the success answer of each
  endpoint.
- **The WebSocket isn't in the schema.** OpenAPI covers HTTP only.
- **No test compares real responses with the schema.** The tests check the schema's description, not live JSON
  against it (see the guide, section 6).
- **Request component names changed** (`ChatCreate` → `ChatCreateRequest`, and so on). No generated client exists
  yet, so nothing breaks.

## Concepts I learned
- [API contracts and OpenAPI](../concepts/api-contracts-and-openapi.md) (new guide).
- [Testing and CI](../concepts/testing-and-ci.md): new notes on skips and class cleanups.

### A skip is not a pass
- **Simple definition:** a skipped test didn't run. The runner prints `OK (skipped=N)`, which looks green.
- **Everyday example:** a smoke alarm with no battery doesn't beep. Silence isn't "no fire".
- **Here:** the place that must run a test (CI's browser job) says so, and there a skip is an error.

### Class cleanups
- **Simple definition:** `cls.addClassCleanup(func, *args)` registers `func` to run after the class's tests,
  **even if `setUpClass` failed half-way**. `tearDownClass` only runs if `setUpClass` finished.
- **Pattern:** register the undo right before the step: "remember the old value, then change it".

## Important code walkthrough

### `chats/test_browser.py`: setup that can fail safely
```python
cls.addClassCleanup(restore_env, 'DJANGO_ALLOW_ASYNC_UNSAFE', os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE'))
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
...
super().setUpClass()
try:
    cls.playwright = sync_playwright().start()
    cls.addClassCleanup(cls.playwright.stop)
    try:
        cls.browser = cls.playwright.chromium.launch()
    except Exception as error:
        if REQUIRED or "Executable doesn't exist" not in str(error):
            raise
        raise unittest.SkipTest(f'needs Chromium: {error}') from error
    cls.addClassCleanup(cls.browser.close)
except BaseException:
    super().tearDownClass()   # the server is running, and tearDownClass won't be called
    raise
```
- `restore_env` puts the old value back, or removes the variable if there wasn't one. The old code always removed
  it, and only on success.
- The server is the one thing that can't be a class cleanup: on success, unittest calls `tearDownClass`, which stops
  it, and a cleanup would stop it twice.

### `chats/test_browser_setup.py`: testing the test base
```python
class Probe(test_browser.BrowserTestCase):   # defined here, so the test runner never collects it
    def test_nothing(self):
        pass

unittest.TestSuite([Probe('test_nothing')]).run(result)
```
- Running a tiny suite inside a test is how you observe class-level behaviour (skip vs error, cleanups) from
  outside. The class is created inside the function, so test discovery never sees it.

### `root/test_schema.py`: no guesses allowed
```python
GENERATOR_STATS.reset()
call_command('spectacular', '--fail-on-warn', '--validate', '--file', path)
```
- drf-spectacular keeps its warnings in a global counter; resetting it first means only this run counts.

## Problems we encountered
- [P-33 · The schema guessed, and a broken browser passed as a skip](../problems-and-solutions.md#p-33--the-schema-guessed-and-a-broken-browser-passed-as-a-skip)
- **A first failing run that proved nothing.** The setup tests patch `test_browser.REQUIRED`, which didn't exist
  yet, so all 6 failed with `AttributeError`. Running them once with `create=True` showed the real old behaviour
  (5 failures, the audit's two symptoms).
- **A failing assertion printed the whole environment.** `assertNotIn('DJANGO_ALLOW_ASYNC_UNSAFE', os.environ)` dumps
  every variable, session tokens included; in CI that would put settings in a public log. It now uses
  `assertIsNone(os.environ.get(...))`. GOTCHA has the rule.
- **My schema test was stricter than OpenAPI.** It expected `{'$ref': ...}` for `participant`, but a read-only
  reference is written `{'allOf': [{'$ref': ...}], 'readOnly': true}` in OpenAPI 3.0. The test helper now accepts
  both.

## Engineering decisions and trade-offs
- [Decision 012](../decisions/012-required-browser-tests.md): a switch in CI, not "required whenever Postgres".
- **A type hint for `is_online`, decorators for the rest:** `-> bool` is enough for a plain value; a nested object
  needs `@extend_schema_field` to name its serializer.
- **`COMPONENT_SPLIT_REQUEST`** changes every request schema's name; accepted because no generated client exists yet,
  and it's the only way to describe an upload correctly.

## What I should remember
- A schema warning is a guess written into the contract. Make the build fail on warnings.
- "Valid OpenAPI" isn't "true OpenAPI": read the file for what the generator can't warn about.
- `OK (skipped=8)` can hide the tests that matter. Where a test must run, make a skip an error.
- Register each undo before its step (`addClassCleanup`); `tearDownClass` doesn't run after a failed `setUpClass`.
- Never `assertIn`/`assertNotIn` against `os.environ`.

## Review questions
1. Why did drf-spectacular ignore our authenticator, when it knows SimpleJWT?
2. What does a client generator do with a `SerializerMethodField` that has no type hint?
3. The schema said `POST /chats/` returns `ChatCreate`. What would a generated client see in the response?
4. Before this fix, what happened in CI if Chromium failed to download?
5. Why can't the live server's shutdown be registered as a class cleanup?
6. Without `REQUIRE_BROWSER_TESTS`, which launch errors still fail, and why?

<details><summary>Answer key</summary>

1. Extensions match the exact class by default (`match_subclasses = False`). `SimpleJWTScheme` targets
   `JWTAuthentication`; ours is a subclass, so it needed its own extension.
2. It falls back to `string`, so `is_online` would be typed as text and `participant` as text instead of an object.
3. An object with no readable fields: `ChatCreate` has only `participant_id`, which is write-only. Everything the
   server actually sends back (`id`, `participant`, `unread_count`, ...) would be missing from the client's type.
4. `chromium.launch()` raised, the broad `except Exception` turned it into `SkipTest`, and the job reported
   `OK (skipped=…)`: green, with no browser test run. `DJANGO_ALLOW_ASYNC_UNSAFE` also stayed `true`.
5. On success, unittest calls `tearDownClass`, which stops the server. A class cleanup runs too, so it would stop
   twice. So `setUpClass` stops it itself, only when it fails after starting it.
6. Every error except Playwright's "Executable doesn't exist". A missing download is a normal local state; any other
   error means something is broken, and a skip would hide it.
</details>

## Next steps
- Merge PR #34, then this PR.
- The Codex audit's 31 findings are all fixed. Left: the risks R-01…R-07 (deployment and measurement), and rerunning
  the baseline load test with the fixed tester (session 014).
