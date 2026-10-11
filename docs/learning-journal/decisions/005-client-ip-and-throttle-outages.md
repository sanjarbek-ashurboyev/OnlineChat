# 005 · Which IP a throttle counts, and what it does when Redis is down

- **Date:** 2026-10-11 · **Status:** Accepted

## Problem
Codex's second audit (H-02, H-03, M-19) found three ways our throttles misbehaved:
- DRF's default (`NUM_PROXIES` unset) takes a client's own `X-Forwarded-For` header as its IP, so one machine could
  make unlimited login attempts by changing the header.
- Registration used `ScopedRateThrottle`, which counts a signed-in request per user, so a token reset the IP limit.
- With Redis down, every throttled request answered 500, including login.

## Options considered
**Client IP**
1. `NUM_PROXIES` from an environment variable (`DJANGO_NUM_PROXIES`), default `0`.
2. Hard-code `NUM_PROXIES = 0` and change it when a proxy arrives.
3. Read IPs ourselves (e.g. `django-ipware`) with a list of trusted proxy addresses.

**Registration**
1. A throttle that always keys by IP (`RegisterIPThrottle`).
2. `authentication_classes = []` on the register view, so nobody is ever signed in there.

**Redis down**
1. Fail open: skip the limit, log a warning.
2. Fail closed: answer 503.

## Chosen
- **IP: option 1.** `0` is safe for how the app runs today (no proxy: [audit OPS-4](../../scaling/01-audit.md)).
  The plan adds Caddy or nginx in Stage 1; that deployment sets `DJANGO_NUM_PROXIES=1` without a code change.
- **Registration: option 1.** It says what it means ("count the IP") and stays correct if authentication is ever added
  to the view. Option 2 also works, but only by a side effect that's easy to undo by accident.
- **Redis down: fail open.** Already chosen in the plan (Decision 0.2, T-21): an outage must not take login down.
  We followed it rather than reopening it.

## Disadvantages and limits
- **`NUM_PROXIES` must match reality.** Too low behind a proxy: everyone shares the proxy's IP and hits 429 quickly.
  Too high without one: clients can forge their IP again. It's a deployment checklist item.
- **Fail open removes brute-force protection during an outage.** Each skipped check logs
  `Throttle cache unavailable`, so the outage is visible, but nothing stops guessing until Redis is back. The 5/min
  per-phone limit is also gone during that time.
- **Not done:** the `/readyz` half of T-21, and the WebSocket frame limits (`chats/ratelimit.py`), which were not part
  of this finding.

## When another option is better
- **Fail closed (503)** if guessing passwords matters more than staying available, e.g. no second factor and a
  targeted user base. Or fail open for most endpoints but closed for login.
- **Trusted proxy list (option 3)** with several proxy layers, or when some clients reach Django directly and others
  through a proxy.
