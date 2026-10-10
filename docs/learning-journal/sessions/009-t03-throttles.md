# 009 · T-03: rate limits on login, registration, refresh, profiles and new chats

- **Date:** 2026-10-10 · **Phase:** Stage 0
- **Task:** T-03 (fixes SEC-3, SEC-4) · **Branch:** `t-03-throttles`
- **Files:** `accounts/throttles.py` (new), `accounts/views.py`, `chats/views.py`, `root/settings.py`,
  `accounts/tests.py`, `chats/tests.py`, docs
- **Objective:** one client can no longer guess passwords, create accounts, walk every user id or start
  chats as fast as it likes. Over the limit it gets **429 Too Many Requests**.

## Before we started
- `docs-gotchas` was already merged (PR #17). Updated `main` and branched `t-03-throttles` from it.
- The `gh` login now shows your renamed account, `sanjarbek-ashurboyev` (checked with `gh api user`).

## What we accomplished
1. **Wrote 8 tests first** (7 limit tests, plus one for a malformed body added with the guard). The 7 limit
   tests **failed** with "got 200/201/401, expected 429": nothing was limited yet.
2. **Added the limits** from [Decision 0.2](../../scaling/02-plan.md):

   | Endpoint | Limit |
   |---|---|
   | `POST /auth/login/` | 20/min per IP **and** 5/min per phone number |
   | `POST /auth/register/` | 5/hour per IP |
   | `POST /auth/token/refresh/` | 30/min per IP |
   | `GET /users/<id>/` | 120/min per user |
   | `POST /chats/` | 30/hour per user (listing chats is not limited) |

3. **Result:** `make test` → **62 tests, OK**. `ruff check .` (0.16.10, as in CI) → clean.
   `makemigrations --check` → no changes.
4. **Checked the guard test can fail:** with the "is the body a dict?" check removed, the malformed-body test
   failed with `AttributeError: 'list' object has no attribute 'get'` (a 500). With the check back, it passes.

**Not done:**
- `NUM_PROXIES` (step 2 of T-03). There's no reverse proxy yet. It must be set when nginx arrives, or
  every user will share the proxy's IP counter.
- The acceptance check "a scripted brute force gets 429, and normal users' p95 is unchanged during the
  attack" needs the running stack and the load-test tooling. It's planned with the baseline load test.
- What happens when Redis is down: DRF throttles then raise an error, so login would fail. That's
  [T-21](../../scaling/03-operations.md) (throttles "fail open").

## Concepts I learned

### Rate limiting
Full guide: [concepts/rate-limiting.md](../concepts/rate-limiting.md). In short, count requests per *who*
(IP, user, phone number) in a time window. Over the limit, refuse with 429 before doing any work.

### Two keys for one endpoint
- **Simple definition:** login has two limits because there are two attacks.
- **One machine, many accounts:** the per-IP limit (20/min) catches it.
- **Many machines (a botnet), one account:** each IP stays under 20, so only the per-phone limit (5/min)
  catches it.
- **Trade-off:** the per-phone limit lets anyone lock a victim out for up to a minute by sending 5 wrong
  passwords for their number. That's why the window is short. CAPTCHA or OTP is the long-term answer.

### Why tests must clear the cache
- `TestCase` rolls the **database** back after each test, but the **cache** (where the counters live) is
  not part of that. A test that fills a counter would leave it full for the next test.
- On SQLite, rolled-back ids are reused, so the next test's "user 1" is often the same id with the
  same counter. That gives an unexpected 429 in a test that has nothing to do with throttling.
- So the throttle tests do `cache.clear()` in `setUp` **and** `self.addCleanup(cache.clear)`.
  `RegisterTests` now clears the cache in `setUp` too: its 5 tests make 6 registration calls
  between them, one more than the limit.

## Important code walkthrough

### `accounts/throttles.py`, the per-phone login throttle
```python
class LoginPhoneThrottle(SimpleRateThrottle):
    scope = 'login_phone'

    def get_cache_key(self, request, view):
        raw = request.data.get('phone_number') if hasattr(request.data, 'get') else None
        if not isinstance(raw, str):
            return None
        number = to_python(raw, region='UZ')
        if not number or not number.is_valid():
            return None  # can't match an account; the IP limit still applies
        return self.cache_format % {'scope': self.scope, 'ident': number.as_e164}
```
- **`get_cache_key` decides *who* is counted.** Returning `None` means "this throttle doesn't apply".
- **`hasattr(request.data, 'get')`:** the body could be a JSON list (`["+998…"]`). Without this check,
  `.get` crashes with a 500 *before* the serializer can return a clean 400.
- **`isinstance(raw, str)`:** the number could arrive as a JSON number or object. Only text is parsed.
- **`to_python(raw, region='UZ')` then `as_e164`:** the same normalisation `UserLookupAPIView` uses.
  `90 123 45 01` and `+998901234501` become the same key, so you can't reset the counter by re-formatting
  the number.
- **Invalid number → `None`:** it can't match an account, so there's nothing to protect per number. The
  IP limit still counts it.

### `chats/views.py`, limiting only POST
```python
class ChatListCreateAPIView(ListCreateAPIView):
    throttle_scope = 'chat_create'

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == 'POST' else []
```
- One view serves both `GET` (list my chats) and `POST` (start a chat). `throttle_classes` would limit
  both, and the client polls the list often.
- **`get_throttles()`** is the DRF method that returns the throttle *instances* for a request. Overriding
  it lets the method decide.
- `ScopedRateThrottle` reads the view's `throttle_scope`, so the rate comes from `chat_create` in settings.

### `root/settings.py`
The rates live in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`. To loosen or tighten a limit during an
incident, change a string here. That's the rollback plan in T-03.

## Problems we encountered
- None new. One near miss, avoided by reading the tests before writing code: `RegisterTests` would have
  hit its own new limit (6 calls, limit 5) because counters survive between tests.

## Engineering decisions and trade-offs
- **Count every attempt, not only failed ones.** Simpler, and the throttle runs before the view, so it
  doesn't yet know whether the password is right. A real user doesn't log in 5 times a minute.
- **IP limits generous, account limits strict** (Decision 0.2): many mobile users share one carrier IP.
- **Didn't limit `GET /chats/`.** It's polled. If it ever needs a limit, it will be a high one, chosen
  from measurements.
- **No new decision record:** the options were already weighed in Decision 0.2 of the scaling plan.

## What I should remember
- A throttle runs **before** the view: a refused request costs almost nothing.
- Pick the key by the attack: per IP, per user, or per target (phone number). Login needs two.
- Normalise the key, or the attacker gets a new counter per spelling.
- The cache isn't rolled back between tests. Clear it.
- Behind a proxy, set `NUM_PROXIES`, or everyone shares one IP.

## Review questions
1. Why does login have both a per-IP and a per-phone limit? Which attack does each one stop?
2. What would happen if `LoginPhoneThrottle` used the raw text from the request instead of `as_e164`?
3. Code reading: why does `ChatListCreateAPIView` override `get_throttles()` instead of setting
   `throttle_classes`?
4. Debugging: after deploying behind nginx, every user gets 429 on login within seconds. What's the
   most likely cause, and what's the fix?
5. Testing: a throttle test passes alone but fails when the whole suite runs. Name a likely cause.
6. Design: what's the downside of the 5/min per-phone limit, and what could replace it later?

<details><summary>Answer key</summary>

1. Per IP: one machine trying many accounts. Per phone: many machines (each under the IP limit) trying
   one account.
2. An attacker could write the same number in many ways (`+998…`, `90 123…`, `901234…`), each with its own
   counter, multiplying the allowed guesses.
3. `throttle_classes` applies to every method. Listing chats (GET) is polled and shouldn't be limited, so
   the throttles are chosen per request method.
4. `NUM_PROXIES` isn't set, so DRF sees nginx's IP for every request. All users share one `login_ip`
   counter, which fills in seconds. Set `NUM_PROXIES` to the number of proxies in front of Django (and make
   sure nginx sets `X-Forwarded-For`).
5. Leftover counters in the cache from an earlier test (the cache isn't rolled back), or the opposite:
   another test filling the same key. Clear the cache in `setUp` and with `addCleanup`.
6. Anyone can lock a user out for up to a minute by sending 5 wrong passwords for their number. Later:
   CAPTCHA after a few failures, or OTP login, instead of a hard block.
</details>

## Next steps
- Review and merge the T-03 PR.
- Next: **T-04** (WebSocket input validation, message rate per socket; COR-3).
- When nginx is added: set `NUM_PROXIES`. Then **T-21**: throttles keep working (fail open) when Redis is down.
