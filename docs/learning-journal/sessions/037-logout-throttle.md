# 037 · Logout blocked by the refresh limit

- **Date:** 2026-10-15 · **Phase:** Stage 1
- **Task:** Codex review of PRs #38–#43, finding "logout blocked by refresh throttle" (T-07, sessions 030 and 036)
  · **Branch:** `t-07-logout-throttle` (stacked on `t-07-refresh-single-use`, PR #46)
- **Files:** `accounts/views.py`, `root/settings.py`, `assets/app.js`, `accounts/tests.py`, `chats/test_browser.py`, docs
- **Objective:** a user who logs out must really end the login, even when the server answers 429 or can't be reached.

## What was done
1. **Reproduced it** (2026-10-13, on `main` `35eb53a`): 30 refreshes from one IP (what a shared NAT or office
   produces in a minute), then a logout from the same IP → **429**. The browser ignored the answer, forgot its tokens
   and the refresh token stayed valid. Two browser tests: a logout answered 429 was never sent again, and a logout the
   network dropped was never sent again.
2. **Server (`accounts/views.py`, `root/settings.py`):** `LogoutView` has its own throttle scope `logout`, 60/min per
   IP, instead of sharing `refresh` (30/min).
3. **Browser (`assets/app.js`):** `logout()` calls `revokeLogin(refresh)`, which sends `POST /auth/logout/` and keeps
   going until the server answers: on 429 it waits for `Retry-After` (at least the current delay), on a network
   error it waits the delay; the delay doubles up to 60 s. The token waits in `localStorage` under `pendingRevokes`
   until the server says 200, 400 or 401 (the token is dead already). On the next page load,
   `pendingRevokes().forEach(revokeLogin)` finishes any that remain. The tab still signs out at once (`signOut()`).
4. **Rebased onto #46** (the WIP commit was based on `main`'s old blacklist logout). Conflicts: `assets/app.js`
   (constants; `logout()` is now only the button, `signOut()` stays #46's), `chats/test_browser.py` (imports; the
   old blacklist assertions). Kept #46's code and the WIP's retry logic and tests.
5. **Checked on #46's code** that the 4 new tests fail without the change (server: `429 != 401`, `429 != 200`;
   browser: `condition never became true` twice), then pass with it.
6. **Results:** `make test` **175 run, OK (skipped=20)** (217 found); real Postgres + Redis with
   `REQUIRE_BROWSER_TESTS=True`, `manage.py test`: **217 OK**, exit 0, no skips; `makemigrations --check` no changes;
   Ruff 0.16.10 clean.

**Not done:**
- The 429 for a *logout* from a tab behind an IP that is itself sending more than 60 logouts a minute can still
  happen; the browser then retries, and the server keeps the login alive until it gets through (a minute at most).
- Pending tokens sit in `localStorage` until confirmed. They are tokens the user asked to end, so a copy gives a
  thief nothing more than they could already do, but until the server answers they are still valid.
- No limit on how many tokens `pendingRevokes` can hold.

## Concepts

### A limit on a safety action
- **Simple definition:** some requests protect the user (logout, "report", "change password"). If a rate limit
  blocks them, the user is less safe, not more.
- **Rule used here:** give it its own counter, so other traffic can't use it up, and make the client keep trying
  until the server confirms.
- **Common mistake:** treating the answer as "nothing to do" because the screen already changed. The tab said
  "logged out"; the server hadn't.
- Extended in [the rate-limiting guide](../concepts/rate-limiting.md).

### Retry with backoff and `Retry-After`
- **Simple definition:** after a failure, wait and send again; wait longer each time (1 s, 2 s, 4 s … 60 s max) so a
  struggling server isn't hammered. A 429 may come with `Retry-After: N` (seconds): the server says when to return.
- **Why here:** the request can fail because of a limit (429) or the network; both mean "try later".

## Walkthrough

`accounts/views.py`:
```python
class LogoutView(TokenViewBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'logout'
```
`ScopedRateThrottle` counts per scope, so `logout` has its own counter next to `refresh`.

`assets/app.js`:
```js
function revokeLogin(refresh, delay = 1000) {
  setPendingRevoke(refresh, true);                 // remember it first, in localStorage
  fetch(`${API}/auth/logout/`, {...}).then((res) => {
    if (res.ok || res.status === 400 || res.status === 401) { setPendingRevoke(refresh, false); return; }
    retry(Math.max(Number(res.headers.get('Retry-After')) * 1000 || 0, delay));   // 429, 5xx
  }, () => retry(delay));                           // network error
}
```
- The token is written down *before* the request: if the page is closed mid-request, the next visit finishes it.
- 400/401 count as done: the token is expired or its login already ended.
- It isn't tied to `state.session`: after logout the session counter has moved on, and the old login must still end.

```js
function logout() {             // the button
  if (state.refresh) revokeLogin(state.refresh);
  signOut();
}
```
Only the button revokes (session 036); `signOut()` is the local part.

## Problems
- **Logout blocked by the refresh limit** → [P-41](../problems-and-solutions.md#p-41--logout-was-blocked-by-the-refresh-limit-and-the-browser-didnt-notice).
- **The branch conflicted with #46.** The WIP commit rewrote `logout()` from the blacklist version; #46 had split it
  into `logout()` and `signOut()`. Resolved by keeping #46's structure and putting the revoke call into `logout()`.

## Decisions
- Own throttle scope for logout, plus a client that retries: [decision 017](../decisions/017-logout-has-its-own-throttle.md).

## What I should remember
- A limit on a request that protects the user needs its own counter.
- "The screen changed" is not "the server agreed". Keep unconfirmed work and retry it.
- Write down what must survive a reload (in `localStorage`) *before* starting the request.

## Review questions
1. Why did 30 refreshes from one IP make a logout fail, and why was nothing shown to the user?
2. Why does `revokeLogin` save the token in `localStorage` before sending the request?
3. Why are 400 and 401 answers treated as "done"?
4. Why isn't `revokeLogin` stopped by `state.session` changing?
5. Why is a separate counter better than raising the `refresh` limit?

<details><summary>Answer key</summary>

1. Logout used the `refresh` scope: 30 requests a minute per IP, shared by everyone behind that IP. The 31st request
   got 429. The browser sent logout without waiting for the answer and signed out locally, so nobody saw the 429.
2. The page can be closed or reloaded before the answer arrives. The saved token lets the next visit send it again.
3. The token is expired, malformed, or its login has already ended: there is nothing left to end.
4. `state.session` changes at every sign-out so that *work for the old account* is dropped. Revoking the old login is
   work that must still happen after the sign-out.
5. A higher shared limit would still let refresh traffic use up logouts. Separate counters can't affect each other.
</details>

## Next steps
- Codex review of this PR (not merged until then).
- With T-10: set `DJANGO_NUM_PROXIES` correctly, or every user behind the proxy shares one logout counter too.
