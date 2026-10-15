# 039 · F-01: `app.js` split into ES modules

- **Date:** 2026-10-15 · **Phase:** Frontend redesign, Phase 1
- **Task:** F-01 in the [frontend plan](../../frontend/plan.md) · **Branch:** `f-01-es-modules`
- **Files:** `assets/app.js` (removed), `assets/js/*.js` (11 new), `templates/index.html`, `GOTCHA.md`,
  `project-overview.md`, docs
- **Objective:** one module per topic before the redesign starts changing the drawing code, with no change in
  behaviour.

## What was done
1. **Baseline first:** the browser tests on unchanged `main` (`4ba822b`), real Postgres + Redis,
   `REQUIRE_BROWSER_TESTS=True`: **46 run, OK**.
2. **Moved the code, line for line,** with a small script: each block of `app.js` went to one module, and the
   script worked out the `import` lines from the names each module uses. Nothing was retyped.

   | Module | Lines | What |
   |---|---|---|
   | `state.js` | 47 | constants, `$`, the shared `state`, `dropped` |
   | `tokens.js` | 151 | saving, renewing (shared, under a Web Lock) and revoking tokens |
   | `api.js` | 42 | `api()`, `errorText()` |
   | `format.js` | 16 | times and "last seen" |
   | `chats.js` | 146 | chat list, "Show more", phone search |
   | `messages.js` | 164 | history, catch-up, lost-echo check, opening a chat, the header |
   | `socket.js` | 167 | the WebSocket, receipts, reconnects |
   | `composer.js` | 60 | the text box and sending |
   | `profile.js` | 36 | profile dialog, `renderMe()` |
   | `session.js` | 130 | login screen, logout, `signOut()`, `start()` |
   | `main.js` | 16 | entry point: names for the tests, the 45 s poll, startup |

3. **Checked the move:** every non-blank line of `app.js` appears in the modules exactly as many times as before
   (a line-count comparison: nothing missing). The only new lines are the `import`s, `export` in front of shared
   names, one section heading, and the `window` line in `main.js`. ESLint 9 (`no-undef`, `no-unused-vars`, run
   from `/tmp`, not added to the project) found nothing; it does report a planted error. Node linked all modules
   with no missing export.
4. **`templates/index.html`** loads `<script type="module" src="{% static 'js/main.js' %}">`.
5. **The tests' globals:** `main.js` puts `state`, `api`, `loadChats`, `start`, `pendingRevokes` and `revokeLogin`
   on `window`. No test changed.
6. **Results:** real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`, `manage.py test`: **223 run, OK**;
   `make test`: **177 run, OK (skipped=20)**; Ruff 0.16.10 clean.

**Not done:**
- No visible change; that starts with F-02.
- `collectstatic` keeps plain file names (no hashes), so after a deploy a browser could mix cached old modules with
  new ones until its cache expires. It was the same for `app.js`; it matters more with 11 files. Worth fixing when
  the deployment is set up (hashed names, or a version in the URL).
- 11 files mean 11 requests on the first load instead of 1; fine on HTTP/2, not measured.

## Concepts

### ES modules
- **Simple definition:** a JS file that shares names with `export` and takes them with `import`; the rest is
  private to the file.
- **Why here:** each topic in its own file, and the dependencies are written at the top of each one.
- Guide: [frontend architecture](../concepts/frontend-architecture.md#es-modules-how-our-code-is-split).

### A refactor proved by unchanged tests
- **Simple definition:** a refactor changes how code is arranged, not what it does. The proof is that the same
  tests pass before and after, *without editing the tests*.
- **Why here:** the browser tests drive a real Chromium, so they check the page, not the file layout.

## Walkthrough

`assets/js/main.js`:
```js
import { state } from './state.js';
import { attemptRevoke, pendingRevokes, revokeLogin } from './tokens.js';
import { api } from './api.js';
import { loadChats } from './chats.js';
import { start } from './session.js';

Object.assign(window, { state, api, loadChats, start, pendingRevokes, revokeLogin });
```
- Importing `main.js` loads every module it needs, and the modules they need, before any of `main.js` runs.
- `Object.assign(window, …)` is the only new behaviour: these names were already visible to the page when
  `app.js` was a classic script, and now only these six are.

`assets/js/socket.js` (top):
```js
import { clearComposerIf, isOurSend, settleSend } from './composer.js';
import { signOut } from './session.js';
```
`composer.js` imports `socketSend` from `socket.js` too: a circular import. It works because neither module calls
the other's functions while loading; they are called later, from event handlers.

## Problems
None. The baseline passed, and so did every run after the move.

## Decisions
- No new decision record: this carries out [018](../decisions/018-plain-js-not-react.md).
- Kept the six test names on `window` instead of rewriting ~40 test lines to `import()` the modules: the tests stay
  unchanged, which is what proves the move.

## What I should remember
- A module's top-level names are private; tests and DevTools only see what `main.js` puts on `window`.
- Prove a refactor with tests that don't change, and run them on the old code first.
- Moving code with a script and comparing line counts beats retyping it.

## Review questions
1. Why was the baseline run on `main` before anything moved?
2. What would break if `main.js` didn't assign anything to `window`?
3. `socket.js` and `composer.js` import each other. Why doesn't that fail?
4. Why can a module's top-level code call `$('chat-list')` safely?
5. What is the risk of 11 un-hashed static files after a deploy?

<details><summary>Answer key</summary>

1. To know the tests pass on the old code in this environment. A failure after the move then points at the move,
   not at a flaky test or the machine.
2. About 40 `page.evaluate` calls in the browser tests (`state.access = 'expired'`, `api(...)`, `loadChats()`…)
   would throw "is not defined". The app itself would still work.
3. Neither calls the other's functions while it is loading. The functions are only called later, from event
   handlers, when both modules have finished loading.
4. Module scripts are deferred: they run after the whole HTML has been parsed, so every element exists.
5. A browser may keep some old modules cached and fetch some new ones, and the mix may not fit together (a missing
   export stops the page). Hashed file names or a version in the URL make each deploy a fresh set.
</details>

## Next steps
- F-02: the design system (colours, type, icons, materials, spring helper, press feedback, reduced motion).
- Choose the bubble colour (green or blue) before F-02 sets the colour roles.
