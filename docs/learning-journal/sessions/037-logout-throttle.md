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
   until the server says 200, 400 or 401 (the server doesn't know the token). On the next page load,
   `pendingRevokes().forEach(attemptRevoke)` finishes any that remain. (Reworked after the review: see the follow-up.) The tab still signs out at once (`signOut()`).
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
- The follow-up's items are listed in its own "Not done".

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
function revokeLogin(refresh) {                    // the follow-up below shows the final version
  setPendingRevoke(refresh, true);                 // remember it first, in localStorage
  fetch(`${API}/auth/logout/`, {...}).then((res) => {
    if (res.ok || res.status === 400 || res.status === 401) { setPendingRevoke(refresh, false); return; }
    retry(Math.max(Number(res.headers.get('Retry-After')) * 1000 || 0, delay));   // 429, 5xx
  }, () => retry(delay));                           // network error
}
```
- The token is written down *before* the request: if the page is closed mid-request, the next visit finishes it.
- 400/401 count as done: the server doesn't know the token. (Round 1 of the review showed an *expired* token
  must not be one of those: see the follow-up.)
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
3. The server doesn't know the token (forged, or not a refresh token), so there is nothing it can end. An *expired*
   token is not in this group any more: the server ends its login (see the follow-up).
4. `state.session` changes at every sign-out so that *work for the old account* is dropped. Revoking the old login is
   work that must still happen after the sign-out.
5. A higher shared limit would still let refresh traffic use up logouts. Separate counters can't affect each other.
</details>

## Next steps
- Codex review of this PR (not merged until then).
- With T-10: set `DJANGO_NUM_PROXIES` correctly, or every user behind the proxy shares one logout counter too.

## Follow-up: Codex review of #47 (round 1)

Codex blocked the PR with three Medium findings in the retry logic I wrote, all reproduced. All three were gaps in
"retry until the server answers"; each is now a test that failed first.

**What was done**
1. **Lost tokens in the queue** (`assets/app.js`). The queue in `localStorage` was read, changed and written back
   in three steps. Two tabs doing it at the same moment each started from the old list, so one write wiped the
   other's token, and that login was never ended. *Reproduced:* two tabs queued 4 tokens each at a chosen
   instant; the queue kept fewer than 8. *Fix:* `updatePendingRevokes(change)` runs the read, change and write
   inside `navigator.locks.request('pending-revokes', ...)`, the lock all tabs of the site share.
2. **A hung logout was never retried.** A request held unanswered is not an error, so `.then(_, retry)` never ran.
   *Reproduced:* the logout held for a simulated 5 minutes was the only attempt; the login stayed renewable.
   *Fix:* `attemptRevoke()` gives each request an `AbortController` with a 10 s limit (`REVOKE_TIMEOUT_MS`); an
   abort lands in the same branch as a network error and is retried.
3. **An expired queued token abandoned a live login** (`accounts/serializers.py`). A token waiting in the queue can
   expire (refresh tokens last a day). The retry then got 401, which the client takes as "done", while a *newer*
   token of the same login still renewed. *Reproduced:* a token of login S renewed once, then its older copy queued
   with an expiry in the past: the server answered 401 and S lived on. *Fix on the server:* `LogoutSerializer`
   checks the signature but not the expiry, then ends the login by `sid`. See decision 017 for why not the client.
4. **Low: a confirmed revoke was sent again.** Tab A's scheduled retry put the token back in the queue after tab B
   had got the server's answer and removed it. *Fix:* a retry first checks the queue and stops if the token is no
   longer there; only `revokeLogin()` adds to the queue, and a retry never does. Cheap once the queue was safe.

**Results:** the 5 new tests (1 server, 4 browser) failed on the PR's code and pass now. `make test` **177 run, OK
(skipped=20)** (223 found); real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`, `manage.py test`: **223 OK**,
exit 0; Ruff 0.16.10 clean; `makemigrations --check` no changes. A server test also checks a forged or an access token
is still refused.

**Not done / limits**
- The queue write now waits for the lock, which takes a few milliseconds. If the user presses Log out while offline
  and the tab is destroyed within those milliseconds, the token isn't stored. Before, the write was synchronous.
- Without `navigator.locks` (an old browser, or plain http away from localhost) the queue race can still happen.
- Two tabs that both load the page each retry the same stored token once; the second answer is harmless (200).

### Concepts
- **A lock around a shared read-change-write.** `localStorage` is shared between tabs, but each tab runs its own
  code, and a "read, change, write" is not one step. Web Locks make tabs take turns. Same idea as the refresh lock
  from session 036; see [the JWT guide](../concepts/authentication-and-jwt.md).
- **Expired is not forged.** A signed token that has expired still proves the server issued it and who it was for.
  It no longer proves the user may *act*; it still proves *which login* to end. Ending a login is safe to allow
  from it, renewing one is not.
- **A request that never answers is a failure too.** Retry logic that only handles errors and refusals misses it;
  every request that a retry loop depends on needs its own time limit.

### Walkthrough (final)
```js
function updatePendingRevokes(change) {
  const run = () => localStorage.setItem('pendingRevokes', JSON.stringify(change(pendingRevokes())));
  return navigator.locks ? navigator.locks.request('pending-revokes', run) : Promise.resolve(run());
}

function revokeLogin(refresh) {                       // adds to the queue, then tries
  void updatePendingRevokes((pending) => (pending.includes(refresh) ? pending : [...pending, refresh]));
  attemptRevoke(refresh);
}

function attemptRevoke(refresh, delay = 1000) {      // tries, and schedules the next try on failure
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REVOKE_TIMEOUT_MS);
  const retry = (wait) => setTimeout(() => {
    if (pendingRevokes().includes(refresh)) attemptRevoke(refresh, Math.min(delay * 2, REVOKE_RETRY_MAX_MS));
  }, wait);                                           // ^ another tab may have removed it meanwhile
  fetch(..., { signal: controller.signal }).then(onAnswer, () => retry(delay)).finally(() => clearTimeout(timer));
}
```
`accounts/serializers.py`, the server side of finding 3:
```python
payload = jwt.decode(raw, token_backend.get_verifying_key(raw), algorithms=[token_backend.algorithm],
                     options={'verify_exp': False, ...})          # signature yes, expiry no
if payload.get('token_type') != 'refresh': raise TokenError('Token has wrong type')
LoginSession.objects.filter(pk=payload.get('sid'), ended_at=None).update(ended_at=timezone.now())
```

### Problems
- The three findings → [P-41](../problems-and-solutions.md#p-41--logout-was-blocked-by-the-refresh-limit-and-the-browser-didnt-notice), follow-up section.
- **Browser tests failed at random when I ran the class four times in a row.** The refresh limit is 30 a minute per
  IP and its counter lives in Redis, so back-to-back runs used it up (`429 != 401`). With 65 s between runs all 15
  passed, twice. Cause **Confirmed** by the `429` in every failure and the passes after the pause. Rule in GOTCHA.
- **A test that passed before failed after the lock.** It reloaded the page right after the click; the queue write
  now waits for the lock, so the reload could come first. The test now waits for the queue entry.

### Decisions
- [Decision 017](../decisions/017-logout-has-its-own-throttle.md), "Update (Codex review of #47)": the server ends the
  login from an expired token; the queue is under a lock; a time limit on every attempt.

### What I should remember
- Any "read, change, write" on shared storage needs a lock (or one atomic operation), even if each step is one line.
- Retry loops need three things: handle refusals, handle failures, and put a time limit on every attempt.
- Never treat an answer as "done" unless you know what it means. 401 meant "I don't know this token" and also
  "this token expired", and the second meant the work was *not* done.

### Review questions
1. Why can two tabs lose a queued token even though `localStorage` calls are synchronous?
2. A fetch hangs for ever. Why does `.then(onAnswer, onError)` never help, and what does?
3. Why can the server end a login from an expired token, when it must refuse to renew one?
4. Why is "keep the newest token per login on the client" weaker than the server ending the login by `sid`?
5. What stops tab A's scheduled retry from sending a revoke tab B already confirmed?

<details><summary>Answer key</summary>

1. Each call is synchronous, but the three steps (read, change, write) are not one step across two tabs. Both tabs
   read the same old list, and the later write replaces the earlier one.
2. A promise that never settles calls neither handler. An `AbortController` timeout turns the hang into an error.
3. The signature proves we issued it and which login it belongs to. Renewing gives someone a new token and so needs
   a live one. Ending a login only takes access away.
4. The client may not know the newest token: another tab renewed it, or the answer was lost. The server always knows
   which login a token belongs to.
5. The retry timer looks at the queue first. Tab B removed the entry, so the retry does nothing and adds nothing.
</details>

### Next steps
- Codex round 2 of #47, the last. Not merged until then.
