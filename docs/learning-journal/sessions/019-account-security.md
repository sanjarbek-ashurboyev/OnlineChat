# 019 · Codex audit: account security (forged IPs, token-reset limits, Redis outages)

- **Date:** 2026-10-11 · **Phase:** Stage 0
- **Task:** findings H-02, H-03, M-17, M-18 and M-19 from [Codex's second audit](../../scaling/05-codex-audit-2026-10-11.md)
  · **Branch:** `fix-account-security`, stacked on `fix-loadtest-seed-safety` (PR #28), so merge #28 first
- **Files:** `accounts/throttles.py`, `accounts/views.py`, `accounts/serializers.py`, `accounts/tests.py`,
  `chats/views.py`, `root/settings.py`, `.env.example`, docs
- **Objective:** IP limits that a client can't dodge, registration that checks passwords against the name and
  survives a race, and login that keeps working when Redis is down.

## Before we started
- Stacked on PR #28 because both PRs edit the audit checklist, `progress.md` and `GOTCHA.md`.
- Read DRF's `BaseThrottle.get_ident` and `ScopedRateThrottle.get_cache_key` in `.venv` before changing anything.
- Checked the plan for the Redis-down rule: Decision 0.2 / T-21 already says throttles **fail open**.

## What we accomplished
1. **Wrote 6 tests first.** On the old code: **3 failures + 2 errors** (forged header, signed-in registration,
   password like the name: failures; Redis down and the registration race: errors). The sixth, "behind one proxy",
   passed already: it sets `NUM_PROXIES` itself and shows the proxy setting works.
2. **H-02, forged IPs:** `REST_FRAMEWORK['NUM_PROXIES']` now comes from `DJANGO_NUM_PROXIES`, default `0`, so DRF uses
   `REMOTE_ADDR` and ignores the header. Documented in `.env.example`.
3. **H-03, a token reset the registration limit:** new `RegisterIPThrottle` always keys by IP.
4. **M-19, Redis down → 500:** `FailOpenMixin` catches `RedisError` in `allow_request`, logs a warning and lets the
   request through. Every throttle in the project uses it, including a fail-open `ScopedRateThrottle` now imported by
   `accounts/views.py` and `chats/views.py`.
5. **M-17, password like the name:** `validate_password` now gets a candidate `User` built from the submitted
   phone number and first name, so `UserAttributeSimilarityValidator` has something to compare with.
6. **M-18, two registrations racing:** `create()` wraps the insert in a savepoint; on `IntegrityError`, if the number now
   exists, it answers the same 400 as the normal duplicate check. Any other database error is re-raised.
7. **Results:**
   - `python manage.py test accounts`: 36 OK. `make test` → **102 run, OK (6 skipped)**. Real Postgres + Redis →
     **108 tests, OK**. `ruff check .` → clean.
   - Against `runserver`: 21 failed logins from one machine, each with a different `X-Forwarded-For` → 20 × 401, then
     **429**.
   - Redis unreachable (`REDIS_PORT=6390`): **old code → 500** (`redis.exceptions.ConnectionError ... Connection
     refused`), **new code → 401** for a wrong password and 400 for a weak registration, with one
     `Throttle cache unavailable` warning per skipped throttle.

**Not done:**
- The rest of T-21: `/readyz`, and the WebSocket frame limits in `chats/ratelimit.py` when Redis is down.
- Atomic counters (audit risk R-02): DRF's throttle reads, then writes, so parallel requests can overshoot a little.
- Production `DJANGO_NUM_PROXIES`: there's no proxy yet. When Caddy/nginx arrives, set it to 1.
- `PublicUserSerializer` etc. unchanged; the privacy finding (M-14) is a later PR.

## Concepts I learned

### `REMOTE_ADDR` vs `X-Forwarded-For`
- **`REMOTE_ADDR`:** the address of the machine that opened the TCP connection. The client can't fake it (for TCP).
- **`X-Forwarded-For`:** a header listing addresses, written by whoever sends the request. A proxy *appends* the
  address it saw, so only the entries added by your own proxies can be trusted: count from the right.
- **Example:** client sends `X-Forwarded-For: 1.2.3.4` (a lie); our one proxy appends the real `203.0.113.1`.
  Header: `1.2.3.4, 203.0.113.1`. With `NUM_PROXIES=1`, DRF takes the last entry, the true one.

### Fail open vs fail closed
- **Fail open:** when a safety check can't run, allow. **Fail closed:** deny.
- **Everyday example:** a fire door unlocks during a power cut (open); a bank vault stays locked (closed).
- We fail open for throttles: availability wins, and the outage is logged.

### Check-then-insert races
- Two requests both check "is this number free?", both see yes, both insert. The **database's unique constraint**
  is the only check that can't race; the app's check is a friendly early message.
- A **savepoint** (`transaction.atomic()` inside another transaction) lets you catch the failed insert and keep
  using the connection. Without it, Postgres refuses every later query in that transaction.

## Important code walkthrough

### `accounts/throttles.py`
```python
class FailOpenMixin:
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.warning('Throttle cache unavailable, %s not applied: %r', type(self).__name__, exc)
            return True
```
- A **mixin** is a small class that adds one behaviour to others. It's listed first
  (`class LoginIPThrottle(FailOpenMixin, throttling.AnonRateThrottle)`), so its `allow_request` runs and
  `super()` calls DRF's.
- It catches `RedisError` only. A bug in our own code still shows up as a 500.

```python
class RegisterIPThrottle(FailOpenMixin, throttling.SimpleRateThrottle):
    scope = 'register_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
```
- `get_ident` is DRF's "which IP?" function, which follows `NUM_PROXIES`. Unlike `ScopedRateThrottle`, it never
  looks at `request.user`.

### `accounts/serializers.py`
```python
candidate = User(phone_number=attrs['phone_number'], first_name=attrs.get('first_name', ''))
try:
    validate_password(attrs['password'], user=candidate)
except DjangoValidationError as exc:
    raise ValidationError({'password': exc.messages}) from exc
```
- `User(...)` builds an object in memory; nothing is saved.
- Django's `ValidationError` is turned into DRF's, keyed by `password`, so the client sees which field is wrong.

```python
try:
    with transaction.atomic():
        return User.objects.create_user(**validated_data)
except IntegrityError:
    if User.objects.filter(phone_number=validated_data['phone_number']).exists():
        raise ValidationError({'phone_number': ['user with this phone number already exists.']}) from None
    raise
```
- The message matches DRF's normal duplicate message, so a client sees one error whichever request lost the race.

## Problems we encountered
- [P-25 · A forged `X-Forwarded-For` header reset the login limit](../problems-and-solutions.md#p-25--a-forged-x-forwarded-for-header-reset-the-login-limit)
- [P-26 · Stopping Docker's Redis didn't stop the app's Redis](../problems-and-solutions.md#p-26--stopping-dockers-redis-didnt-stop-the-apps-redis)
- **A shell loop wiped `PATH`.** I named a loop variable `path`; in zsh that *is* `PATH` (as an array), so every
  following command was "not found". Nothing changed (the `git stash` commands were among those that didn't run).
  Renamed and reran.
- **Fail-open warnings cluttered the test output.** The test now captures them with `assertLogs`, which also checks
  that each outage is logged (3 records: login IP, login phone, refresh).

## Engineering decisions and trade-offs
- [Decision 005](../decisions/005-client-ip-and-throttle-outages.md): `NUM_PROXIES` from the environment (default 0),
  an always-by-IP registration throttle, and fail open (following plan Decision 0.2).
- **Fail open everywhere, not just on auth views:** the finding was about login, but one rule for all throttles is
  easier to reason about than a mix (the "two doors" lesson, P-20).

## What I should remember
- Unset is a value. DRF's unset `NUM_PROXIES` trusts a header any client can write.
- An IP limit must be keyed by IP whether or not the request is signed in.
- The database constraint is the only uniqueness check that can't race; catch its error and answer 400.
- Give `validate_password` the user, or the similarity check silently does nothing.
- Before testing "X is down", check which X the app is connected to.

## Review questions
1. With `NUM_PROXIES` unset, what does DRF use as the client's identity when `X-Forwarded-For` is present?
2. Behind exactly one proxy, why take the *last* entry of `X-Forwarded-For`, not the first?
3. Why did a JWT let someone keep registering after the IP limit was used up?
4. What would go wrong without the `transaction.atomic()` around `create_user` on Postgres?
5. Name one risk of failing open, and what we do to notice it.
6. `docker compose stop redis` didn't make login fail. Why?

<details><summary>Answer key</summary>

1. The whole header, as one string (spaces removed). A client can put anything there, so each request can have a new
   "IP".
2. The proxy appends what it saw, so the last entry was written by our proxy. Earlier entries came from the client
   and can be forged.
3. `ScopedRateThrottle` counts signed-in requests per user id. With a token, the counter switched from the IP
   (full) to that user (empty), and every new account gave another token.
4. The failed insert aborts the outer transaction. The `exists()` check after it would raise "current transaction is
   aborted", a 500 again. The savepoint rolls back only the insert.
5. No brute-force limit while Redis is down (including the per-phone 5/min). Each skipped check logs
   `Throttle cache unavailable`, so the outage shows up in the logs.
6. A Homebrew Redis listens on `127.0.0.1:6379`, and the app connects to `localhost:6379`, i.e. Homebrew's.
   Docker's container wasn't the one in use.
</details>

## Next steps
- Merge PR #28, then this PR (the branch is stacked on #28's).
- Decide whether to keep the Homebrew Redis (`brew services stop redis` makes Docker's the one in use, like Postgres).
- Next audit group: WebSocket hardening (H-01, M-01, M-02, M-05).
