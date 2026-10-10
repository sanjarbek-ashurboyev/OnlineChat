# Rate limiting (throttling)

*First used in [session 009](../sessions/009-t03-throttles.md) (T-03).*

## 1. Simple definition

A **rate limit** caps how many times one caller can do one action in a window of time, such as
"5 login attempts per minute per phone number". When the caller goes over it, the server
refuses with **HTTP 429 Too Many Requests** and doesn't do the work. DRF calls this a **throttle**.

## 2. Why it exists

Without a limit, every request is served at full cost, however many there are.
- **Login is expensive on purpose.** Checking one password takes about 200 ms of CPU
  ([SEC-3](../../scaling/01-audit.md)). That's what makes stolen password hashes slow to crack. It
  also means one script can keep a CPU busy just by guessing passwords.
- **Some actions leak or create data.** User ids are sequential (1, 2, 3…), so `GET /users/<id>/`
  in a loop lists every user. `POST /chats/` in a loop lets one account message everyone
  ([SEC-4](../../scaling/01-audit.md)).

At low traffic, abuse is the *only* thing that can overload you. A limit turns "unbounded" into
"at most N per minute".

## 3. How it works here, step by step

1. A request reaches a DRF view. Before the view's code runs, DRF calls `allow_request()` on each
   class in the view's `throttle_classes`.
2. Each throttle builds a **cache key** saying *who* is counted, e.g. `throttle_login_phone_+998901234501`.
   If it returns `None`, that throttle doesn't apply to this request.
3. The throttle reads, from the cache (Redis in production), the list of times this key made a request.
   It drops the ones older than the window (1 minute, 1 hour…).
4. If the list is already full (5 entries for `5/min`), the request is refused: **429**, plus a
   `Retry-After` header saying how many seconds to wait.
5. Otherwise it appends "now" to the list, saves it, and the view runs normally.

Every request counts, whether it succeeds or not, because the throttle runs *before* the view.

## 4. Small example

```python
# settings.py
REST_FRAMEWORK = {'DEFAULT_THROTTLE_RATES': {'refresh': '30/min'}}

# views.py
class CustomTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'
```
The 31st refresh from one IP within a minute gets 429. A minute later, the oldest entries have left the
window, and requests work again.

## 5. In our project

| Endpoint | Scope | Rate | Counted per | Why |
|---|---|---|---|---|
| `POST /auth/login/` | `login_ip` | 20/min | IP | One machine guessing many accounts |
| `POST /auth/login/` | `login_phone` | 5/min | Phone number | Many machines guessing one account |
| `POST /auth/register/` | `register_ip` | 5/hour | IP | Mass fake accounts |
| `POST /auth/token/refresh/` | `refresh` | 30/min | IP | Cheap to call, no reason to call often |
| `GET /users/<id>/` | `profile_read` | 120/min | User | Walking every id |
| `POST /chats/` | `chat_create` | 30/hour | User | Messaging everyone |
| `GET /users/lookup/` | `user_lookup` | 20/hour | User | Already there before T-03 |

The DRF classes we use:
- **`ScopedRateThrottle`**: counts a signed-in user by their id, and anyone else by IP. The rate comes from
  the view's `throttle_scope`. One scope per view.
- **`AnonRateThrottle`**: counts by IP, only for requests that aren't signed in. Our `LoginIPThrottle`
  subclasses it. The login view has no authentication, so every login request counts.
- **`SimpleRateThrottle`**: the base class. Our `LoginPhoneThrottle` subclasses it and overrides
  `get_cache_key` to count by the phone number in the request body (`accounts/throttles.py`).

The rates live in `root/settings.py`, so changing a limit doesn't need a code change.

## 6. Alternatives

| Option | Sees | Good for | Can't do |
|---|---|---|---|
| **App throttles (DRF)**, what we use | User, phone number, IP, URL | Business rules ("5 logins per number") | Stop traffic before it reaches Python |
| **Reverse proxy** (nginx `limit_req`) | IP, URL | Cheap, coarse floods | Anything about accounts |
| **Edge WAF/CDN** (e.g. Cloudflare) | IP, browser fingerprint, reputation | Big distributed attacks, bots | Your business rules |
| **Token bucket in memory** | One WebSocket | Messages per socket (T-04) | Limits shared across processes |

The plan ([Decision 0.2](../../scaling/02-plan.md)) uses app throttles now, adds nginx in Stage 1 and an edge
WAF later. They stack: each layer catches what the others can't see.

## 7. Common mistakes

- **Counting the proxy instead of the client.** Behind nginx or a load balancer, every request comes from
  the proxy's IP, so all users share one counter. Set DRF's `NUM_PROXIES` when a proxy is added. We have
  no proxy yet.
- **Per-IP limits that are too strict.** Mobile carriers and offices put many people behind one IP. Keep IP
  limits generous and per-account limits strict.
- **Not normalising the key.** `90 123 45 01` and `+998901234501` are the same account. Without
  normalising, an attacker gets a fresh counter for every way of writing the number.
- **A cache that isn't shared.** Django's `LocMemCache` counts per process. With 4 processes, the real
  limit becomes 4× the setting. Production uses Redis, which is shared. Tests use `LocMemCache`, which is fine for one process.
- **Tests that leak counters.** The cache outlives a test's database rollback. A test that fills a
  counter must clear the cache afterwards, or a later test gets an unexpected 429.
- **Forgetting the lockout side effect.** Anyone can block a victim's login for a minute by
  sending 5 wrong passwords for their number. Keep windows short. Later, add CAPTCHA or OTP instead of a hard block.

## 8. When to use it

On every endpoint that is **expensive** (password hashing, sending SMS), **creates permanent data**
(accounts, chats, messages), or **reveals data one item at a time** (lookup by id or phone number). Polled
read endpoints (our chat list) usually don't need one until they show up in measurements.
