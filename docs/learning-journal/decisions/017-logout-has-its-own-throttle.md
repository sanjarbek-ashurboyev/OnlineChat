# 017 · Logout has its own throttle, and the browser retries it

- **Date:** 2026-10-15 · **Status:** Accepted (Codex review of #38–#43, session 037)

## Problem
`POST /auth/logout/` shared the `refresh` throttle (30/min per IP). Behind a shared NAT, other people's refreshes
could make logout answer 429, and the browser ignored the answer: the tab was signed out, the login was not (P-41).

## Options considered
1. **No throttle on logout.** It needs a valid refresh token, so guessing is pointless. But every call still parses
   and verifies a JWT, and a flood of garbage costs CPU.
2. **Keep the shared `refresh` scope** (before). Other traffic can use up the logouts.
3. **Its own scope, 60/min per IP.** Refreshes can't affect it; a flood is still bounded.
4. **Raise the `refresh` limit.** Still shared, and it weakens the limit that protects refresh.

And for the client: **ignore the answer** (before) or **retry until the server answers**.

## Chosen: 3, with a retrying client
60 a minute is twice the refresh rate and far above what one person does. The client keeps the token in
`localStorage` until the server answers 200, 400 or 401 (it doesn't know the token), waits for `Retry-After` on a 429, and backs off on network
errors (1 s doubling to 60 s).

## Disadvantages and limits
- The counter is per IP like the others, so with `DJANGO_NUM_PROXIES` wrong, everyone shares it (P-25).
- Between a refused logout and the retry, the login is still valid (a minute at most for a throttle).
- Tokens waiting to be revoked sit in `localStorage`.

## When another option is better
- **1** if logout ever becomes expensive to throttle correctly (e.g. throttling by login session instead of IP).

## Update (Codex review of #47, round 1): an expired queued token
A queued token can expire before its retry. The server answered 401 and the client dropped it, but a newer token of
the same login still renewed (session 037). Options:
1. **The client keeps the newest token per login** and revokes with that. It can't always know it: another tab may
   have renewed, or a renewal's answer may have been lost, so the newest token isn't in this browser.
2. **Treat 401 as "retry later"** on the client. A forged token would then be retried for ever.
3. **The server ends the login from any token with a valid signature, expired or not.** It always knows which login
   a token belongs to, through `sid`.

**Chosen: 3.** An expired token still proves we issued it and which login it names. What it no longer proves is
that the holder may *use* the login, so refresh keeps refusing it. Ending a login only takes access away, and the
sign-out of someone with a stolen expired token is something a stolen live token could do already. Forged tokens
(wrong signature) and access tokens still get 401. The client's rule stays: 200, 400 and 401 end the retrying.

Two smaller changes: the queue's read-change-write runs under a Web Lock shared by all tabs (decision against
"last write wins"), and every attempt ends after 10 s, so a hung request is retried like a failed one.

**Limit:** a refresh token that expired *and* whose login row was deleted gets 200 and nothing happens, which is right.

