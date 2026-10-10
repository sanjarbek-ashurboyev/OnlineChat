# 3. Risk register, backlog, release strategy, cost and readiness

---

## 3.1 Risk register

Likelihood and impact are judged for **the stage where the risk becomes relevant**,
with the reasoning in the "Trigger" column. "Detect" says how you'd know; "Verify"
says which test proves the mitigation works.

| ID | Risk | Root cause / component | Trigger | L / I | Detect | Prevent | Recover | Verify |
|---|---|---|---|---|---|---|---|---|
| R-01 | Account takeover via forged JWT | `SECRET_KEY` public (SEC-1) | Any deploy with the committed key | High / Critical | Can't detect forged tokens; that's why it's critical | T-01 rotate + env | Rotate key (logs everyone out) | Test: token signed with the old key → 401 |
| R-02 | Password guessing / CPU exhaustion via login | No throttle; 200 ms CPU/attempt (SEC-3) | Public URL | High / High | Login failure rate, CPU, 429s | T-03 | Block IPs at proxy; tighten limits | Scripted brute force gets 429 |
| R-03 | Mass scraping of users + spam to everyone | Unthrottled `/users/<pk>/`, `POST /chats/`, free accounts (SEC-4) | First abusive user | Medium / High (privacy) | Per-user request counts; chats created per user/day | T-03, T-05, later OTP (T-36) | Disable account; purge spam chats | Enumeration loop gets 429 |
| R-04 | Database bloat from huge/flooded messages | No size/rate limit (SEC-5) | One malicious client | Medium / High | Table growth rate; messages/user/min | T-04 | Delete offending rows; `VACUUM` | 1 MiB message rejected; 11th message in 1 s rejected |
| R-05 | Messages "missing" after reconnect | At-most-once channel layer + no gap fetch (COR-1) | Every deploy/network blip | High / Medium | Support reports; test | T-09 | User reopens chat | Disconnect/send/reconnect test |
| R-06 | Ghost "online" users, Redis group leaks | Exception in `disconnect` (COR-2) | Burst disconnects (measured: 97/200) | High / Low | Presence count vs socket count; Redis memory | T-02 | TTL heals presence in 90 s | Test with a mocked `group_discard` failure |
| R-07 | Latency collapse under spikes | One WS DB thread × 6.5 ms per call (PERF-1/2) | ~100 DB calls/s per process | High at stage 1 / High | `message_delivery_seconds` p95; thread queue time | T-13, T-15, T-16 | Add a process (T-22) | Load test before/after |
| R-08 | `too many clients` from Postgres | Per-request connections, unbounded HTTP threads (PERF-8) | ~95 concurrent HTTP requests | Medium / High | PG connection count; 500s with `OperationalError` | T-13 pool caps it | Restart app; raise limits temporarily | HTTP-only load test |
| R-09 | Chat list gets slower every week | Read-time aggregate over all history (PERF-5) | Data growth + poll rate | High (gradual) / Medium | `pg_stat_statements`; endpoint p95 trend | T-17, T-24, T-25 | Temporarily raise poll interval in client | `EXPLAIN` on heavy user |
| R-10 | Reconnect storm after deploy | No jitter (COR-4), all sockets drop at once | Every deploy at scale | High / Medium | Connect rate spike; p95 spike after deploy | T-09 jitter, T-27 graceful close | Wait; temporarily cap connect rate | Restart-under-load test |
| R-11 | Data loss | No backups (OPS-6) | Disk failure, bad command | Medium / Critical | Backup job alerts; restore drills | T-14 | Restore from backup | Monthly restore drill |
| R-12 | Migration locks the message table | `CREATE INDEX` / `ALTER` without `CONCURRENTLY` on a big table | Stage 1+ table sizes | Medium / High | Deploy hangs; lock waits in `pg_stat_activity` | Migration rules (§3.4), `lock_timeout` | Cancel migration; retry concurrently | Rehearse on a staging copy |
| R-13 | Irreversible migration can't be rolled back | Dropping columns/tables in the same release as the code change | Contract step | Medium / High | Code review | Expand/contract with a ≥ 1-week gap | Restore from backup (painful) | Rollback rehearsal in staging |
| R-14 | Redis outage takes the whole app down | Throttles raise on cache errors; channel layer down (OPS-8) | Redis restart/failover | Medium / High | `/readyz`; error rate | T-21 fail-open throttles; managed Redis with replica | Restart/fail over Redis; clients reconnect | Stop Redis during a load test |
| R-15 | Forged messages via exposed Redis | `compose.yaml` exposes 6379 with no auth (SEC-9) | Compose used on a public VM | Low / Critical | Port scan of own server | T-10 | Firewall; rotate | `nmap` from outside shows only 80/443 |
| R-16 | Token leaks via logs | JWT in WS query string (SEC-8) | Reverse proxy default log format | Medium / Medium | Grep logs for `token=` | T-20 log format / socket ticket | Rotate key if leaked broadly | Log grep in CI smoke test |
| R-17 | Stolen refresh token valid 24 h | No rotation/blacklist (SEC-7) | XSS or device theft | Low / High | — | T-07, CSP | Blacklist token / rotate key | Logout → refresh token rejected |
| R-18 | Disk full from avatars | No size limit, local disk (SEC-6) | Abuse | Low / High | Disk usage alert | T-06, T-31 | Delete files; resize disk | Upload 10 MB → 400 |
| R-19 | Dependency vulnerability | Unpinned, unscanned deps (SEC-10) | Any CVE | Medium / Varies | `pip-audit`, Dependabot | T-08 | Patch release | CI fails on known CVE |
| R-20 | Silent background job failure | (Future) queue without monitoring | Stage 2 (T-28) | Medium / Medium | Queue depth, job age, failure count | Dead-letter handling, alerts | Replay idempotent jobs | Kill worker mid-job test |
| R-21 | Duplicate messages on retry | No idempotency key (stage 2 F) | Flaky mobile networks | Medium / Low | Identical consecutive messages | T-37 `client_msg_id` | — | Send same `client_msg_id` twice → one row |
| R-22 | Replica lag shows stale history | Read replica (stage 2, on trigger) | If T-34 is built | Medium / Medium | Replication lag metric | Read-your-writes routing | Route reads to primary | Lag injection test |
| R-23 | Runaway cost (SMS pumping, egress, autoscaling) | Usage-based services | Stage 2 | Medium / High | Budget alerts, per-service spend | Spend caps, quotas, rate limits | Disable feature / cap | Budget alert test |
| R-24 | Privacy breach via logs/errors | Logging message text, phone numbers, tokens | Any logging change | Medium / High | Log review; Sentry PII scrubbing | Logging policy (T-12) | Purge logs; incident procedure | Test asserts scrubbing |
| R-25 | Wrong conclusions from load tests | Generator on the same machine; unrealistic data | Every test | High / Medium | Generator CPU high; results don't match production | §2.4 rules | Re-run correctly | Compare with production metrics |

**How to keep finding new risks** (bugs you can't predict yet):
1. After every incident, write a 1-page post-mortem (what happened, why, what detects it next time) and add a row here.
2. Every new feature PR answers: "What happens if this is called 1,000×/s? Twice concurrently? While Redis is down?"
3. Quarterly, re-run the full test suite in §3.3 and review this table.

---

## 3.2 Implementation backlog

**Priority:** C = critical, H = high, M = medium, L = low. **Next?** = prerequisite for the next stage.

### Category 1 · Critical security and data-integrity fixes (Stage 0)

**T-01 · Settings from environment, rotate secret** · C · 2–4 h · Next? yes
- **Status (2026-10-10): done.** Env-based settings landed on `main` in `763c9da`. PR #6 added the HTTPS settings, `CSRF_TRUSTED_ORIGINS`, the forged-token tests and `check --deploy` in CI.
- **Problem:** SEC-1, SEC-2, OPS-7. **Why now:** a breach at any scale.
- **Files:** `root/settings.py`, `.env` (local only), new `.env.example`.
- **Steps:**
  1. `SECRET_KEY = os.environ['DJANGO_SECRET_KEY']`.
  2. `DEBUG = os.environ.get('DJANGO_DEBUG') == '1'`.
  3. `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from comma-separated env.
  4. When not DEBUG: `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS.
  5. Generate a new key.
- **Tests:** settings test; `check --deploy` in CI with production env.
- **Acceptance:** no secret in the repo; `check --deploy` clean.
- **Deploy/rollback:** config-only; rollback = previous config (but never the old key).

**T-02 · `disconnect()` always marks offline** · H · 1 h · Next? no
- **Status (2026-10-10): done** (branch `t-02-disconnect-marks-offline`). Root cause: channels-redis uses one redis-py `ConnectionPool` per process, with `max_connections=100` by default, and it raises `MaxConnectionsError` instead of waiting. Pool sizing (or a blocking pool) is left for Stage 1 with a load test. The load-test acceptance check is still to run.
- **Problem:** COR-2 (measured 97 failures).
- **Files:** `chats/consumers.py:68-73`.
- **Steps:** wrap `group_discard` in `try/except Exception` + `logger.exception`, and
  `mark_offline` + `touch_last_seen` in `finally`. Also investigate the `MaxConnectionsError`
  root cause (channels_redis connection pool under a burst) and record it.
- **Tests:** a `WebsocketCommunicator` test with `group_discard` patched to raise; assert the presence set is empty.
- **Acceptance:** the load test's end-of-run disconnects produce no presence leftovers.

**T-03 · Throttles for auth, enumeration and chat creation** · C · 3–6 h · Next? yes
- **Problem:** SEC-3, SEC-4.
- **Files:** `accounts/views.py`, `chats/views.py`, `root/settings.py`, new `accounts/throttles.py` (phone-keyed login throttle).
- **Steps:**
  1. Add `throttle_classes` per view (rates in Decision 0.2).
  2. Set `NUM_PROXIES` once a proxy exists.
- **Tests:** N+1th request → 429 per scope; different phone/IP unaffected.
- **Acceptance:** scripted brute force gets 429 after the limit; normal-user p95 unchanged during the attack.
- **Rollback:** raise rates via settings (no code change).

**T-04 · WebSocket input validation, max length, per-socket rate limit** · C · 3–5 h · Next? yes
- **Problem:** SEC-5, COR-3.
- **Files:** `chats/consumers.py:75-118`, `chats/serializers.py` (`max_length` on `text`), `chats/models.py` (optional DB `CHECK (length(text) <= 4000)` via migration).
- **Steps:**
  1. Type checks on the payload.
  2. `TokenBucket` (Decision 0.2).
  3. Cap sockets per user at connect.
- **Tests:** list payload → error frame, socket stays open; 4,001-char text rejected; burst of 20 → 10 accepted.
- **Acceptance:** none of the abuse tests crash the consumer.

**T-05 · Who can start a chat; enumeration-safe responses** · H · 1–3 h + **product decision** · Next? yes
- **Options:**
  - (a) Keep "anyone by id", but throttle (T-03).
  - (b) Chat creation requires the phone number (merge lookup + create into one throttled endpoint).
  - (c) Message requests that the recipient must accept.
- **Recommendation:** (b) now, (c) if spam appears.
- **Files:** `chats/serializers.py`, `accounts/views.py`, `assets/app.js` lookup flow.

**T-06 · Avatar limits; remove media from git** · M · 1–2 h · Next? yes (before T-31)
- **Steps:**
  1. Validator: ≤ 2 MB and ≤ 4096×4096 px.
  2. `git rm --cached -r media/`, then add `media/` to `.gitignore`.
- **Tests:** oversize upload → 400.

**T-07 · Refresh rotation and server-side logout** · M · 2–4 h · Next? no
- **Steps:**
  1. `SIMPLE_JWT = {'ROTATE_REFRESH_TOKENS': True, 'BLACKLIST_AFTER_ROTATION': True}`.
  2. Add `rest_framework_simplejwt.token_blacklist` to apps and run its migration.
  3. Logout endpoint blacklists the refresh token; the client calls it.
- **Trade-off:** one DB write per refresh (every 5 min per online user: C/300 writes/s, small).
- **Tests:** after logout, refresh → 401.

**T-08 · Complete, pinned dependencies** · H · 1–2 h · Next? yes
- **Status (2026-10-10): done.** Started in `763c9da` and `6267925`. PR #7 added `requirements.in`, the full pins for Python 3.13, psycopg 3, `pip-audit` in CI and Dependabot.
- **Steps:**
  1. `requirements.in` (direct deps) → `pip-compile` → pinned `requirements.txt`.
  2. Include `channels`, `channels-redis`, `daphne`, `redis`, `psycopg[binary,pool]`; drop `psycopg2-binary`.
  3. Add `pip-audit` to CI and Dependabot.
- **Acceptance:** fresh venv + `pip install -r requirements.txt` + tests pass.

**T-09 · Gap fetch + reconnect jitter** · C · 4–8 h · Next? yes (**foundation for all later deploys**)
- See Decision 0.3.
- **Files:** `chats/views.py` (`?after=`), `assets/app.js` (`onopen`, backoff).
- **Tests:** reconnect test; COR-5 check.

**T-11 · Test suite + CI** · C · 1–2 days · Next? yes
- **Status (2026-10-10): done** (PR #5, then PR #14). 53 tests. CI runs Ruff; tests on SQLite with the test settings; tests on **Postgres 17 + Redis 7** with the normal settings; `makemigrations --check`; `check --deploy`; `pip-audit`; and **gitleaks** over the full history. The WebSocket tests use `TransactionTestCase`. The T-02/T-04/T-09 tests come with those tasks. The suite uses Django's runner, not pytest, which is fine.
- **Files:** `pytest.ini`, `conftest.py`, `accounts/tests/`, `chats/tests/`, `.github/workflows/ci.yml`.
- **Minimum set:**
  - Register/login/refresh.
  - Access control: a non-member gets 404 on `/chats/<id>/messages/` and an error frame over WS.
  - Message send over WS (`WebsocketCommunicator`) and REST.
  - Read receipts.
  - Throttles; T-02/T-04/T-09 tests.
  - The chat list returns correct `unread_count` (protects T-17 later).
- **CI:** Postgres + Redis services; `pytest`, `check --deploy`, `makemigrations --check`, `pip-audit`, `gitleaks`.

### Category 2 · Baseline measurement and observability

**T-10 · Production deployment setup** · C · 1–2 days · Next? yes
- **Steps:**
  1. Dockerfile (or systemd unit) running daphne.
  2. Caddy/nginx with TLS, WS upgrade, timeouts, body limit, log format without the query string.
  3. Static via `collectstatic`.
  4. `compose.prod.yaml` with no public DB/Redis ports and a Redis password.
  5. Fix the dev port clash (use `5433:5432` locally, or stop the Homebrew Postgres).

**T-12 · Observability + measurement** · C · 2–4 days, incremental · Next? yes
- **Steps:**
  1. JSON logs with a request id and a PII policy.
  2. Sentry.
  3. `/healthz`, `/readyz`.
  4. `pg_stat_statements`.
  5. Metrics (stage 1, section G).
  6. Extend `loadtest/run.py`: `--scenario reconnect-storm|http-only`, heavy-user seeding.
  7. Store results under `loadtest/results/<date>-<commit>.json`.
  8. Profile one load test with `py-spy` to confirm PERF-1/PERF-4 (or refute them).

**T-14 · Backups + restore drill** · C · 0.5–1 day · Next? yes
- **Steps:**
  1. Managed snapshots + PITR, or a nightly `pg_dump -Fc` to object storage.
  2. A scripted restore into a scratch DB with row-count checks.
  3. Calendar the monthly drill.

### Category 3 · Required for Stage 1 (1,000 online)

| ID | Task | Pri | Effort | Depends on | Files | Acceptance |
|---|---|---|---|---|---|---|
| T-13 | Django psycopg 3 connection pool (Decision 2.1) | H | 2–4 h | T-08, T-12 | `root/settings.py` | DB time per WS call < 1 ms p95; load test ceiling recorded before/after |
| T-15 | `touch_last_seen` at most once per 60 s per socket | H | 1–2 h | T-11 | `chats/consumers.py` | DB calls per message drop by 2 (measured via query counter) |
| T-16 | Async presence (`redis.asyncio`) | M | 3–5 h | T-11 | `chats/presence.py`, `chats/consumers.py`, `accounts/serializers.py` | No `sync_to_async(presence…)` left on the WS path; same behaviour in tests |
| T-17 | Chat list rewrite + partial index (Decision 2.3) | H | 4–8 h | T-11 (unread tests), T-12 (`EXPLAIN` baseline) | `chats/views.py`, `chats/models.py`, migration (concurrent) | Count query without GROUP BY; identical results; heavy-user `EXPLAIN` buffers ↓ |
| T-18 | Cursor pagination for history (expand/contract) | M | 4–6 h | T-09 | `chats/views.py`, `assets/app.js` | Deep page latency flat; no duplicates/gaps in test |
| T-19 | Drop redundant indexes | L | 1 h | T-12 (measure) | migration (`RemoveIndexConcurrently`) | Insert cost measured before/after |
| T-20 | WS token never logged (proxy log format, later socket ticket) | M | 1–4 h | T-10 | proxy config / `chats/middleware.py` | `grep token=` on logs empty |
| T-21 | Redis failure behaviour: throttles fail open, `/readyz` reports it | M | 2–4 h | T-03 | `root/settings.py`, custom throttle cache handling | Stop Redis: REST still answers, 5xx rate < 1% |
| T-22 | Second app process + cross-process test | M | 2–4 h | T-13 | proxy config | A on process 1, B on process 2 exchange messages |
| T-29 | Cache chat membership on the socket (optional) | L | 2 h | T-13 + profile showing `get_chat` matters | `chats/consumers.py` | Only if profiling justifies it |

### Category 4 · Required for Stage 2 (10,000 online), each with its trigger

| ID | Task | Trigger | Effort |
|---|---|---|---|
| T-23 | HTTP (gunicorn) / WS (daphne) process split + load balancer path routing | Second server needed (availability) | 2–4 days |
| T-24 | `/presence/` endpoint (Redis only) replacing the 45 s chat list poll | Chat list in top 3 of `pg_stat_statements` by total time | 0.5–1 day |
| T-25 | `ChatMember` inbox model (expand → dual-write → backfill → verify → switch → contract) | Chat list p95 > SLO for heavy users after T-17 | 1–2 weeks |
| T-26 | Per-user message rate limit across processes (Redis sliding window) | More than one WS process | 0.5 day |
| T-27 | Graceful WS shutdown in batches (close code 1012) | Rolling deploys | 0.5–1 day |
| T-28 | Background job runner + idempotent jobs | First slow/external operation | 1–3 days |
| T-30 | Managed Postgres with standby + PITR; failover drill | 99.9% availability target | 1–2 days |
| T-31 | Object storage for avatars (`django-storages`) + CDN | Second app server | 1 day |
| T-36 | Phone verification (OTP) with spend cap | Spam/fake accounts measured | 2–4 days |
| T-37 | `client_msg_id` idempotency | Duplicate-send reports or mobile client | 1 day |

### Category 5 · Only when the trigger fires (during Stage 2)

| ID | Task | Trigger |
|---|---|---|
| T-32 | PgBouncer (transaction mode) | Σ(processes × pool) > 60–70% of `max_connections` |
| T-33 | Message retention + monthly partitioning | Vacuum/index/backup times or retention requirements |
| T-34 | Read replica with read-your-writes routing | Primary CPU > 60% at peak, reads dominant |
| T-35 | WS autoscaling; channel layer sharding | Sockets/process limit reached; Redis CPU > 60% |

### Ordering: quick wins, parallel work, sequential chains

- **Quick wins (≤ 2 h each, do this week):** T-01, T-02, T-06, T-08.
- **Must be sequential:**
  - T-11 (tests) before any refactor (T-13 … T-18), so you can prove behaviour didn't change.
  - T-12 (baseline numbers) before T-13/T-15/T-17, so you can prove they helped.
  - T-09 before T-27, T-30 or anything that drops sockets.
- **Can run in parallel:** T-03/T-04/T-05 (different files); T-10 alongside T-11.
- **High-risk migrations:** T-17 (index on the message table: concurrent build), T-18
  (API contract: expand/contract), T-25 (data model: full expand/contract with backfill), T-33 (partitioning).

---

## 3.3 Testing strategy

| Layer | Tool | Covers | When |
|---|---|---|---|
| Unit | pytest | TokenBucket, validators, presence helpers | Every commit |
| API | DRF `APIClient` | Auth, permissions, throttles, pagination contract | Every commit |
| WebSocket | `channels.testing.WebsocketCommunicator` | Connect/auth, send, read, errors, disconnect, gap fetch | Every commit |
| Query budget | `CaptureQueriesContext` / `assertNumQueries` | No N+1, no accidental extra aggregate | Every commit |
| Concurrency | threads/asyncio in tests | Duplicate chat creation, double read, duplicate `client_msg_id` | Every commit |
| Migration | `makemigrations --check`, `sqlmigrate` review, staging rehearsal | Locks, reversibility | Every migration |
| Load / stress / soak / spike | `loadtest/run.py` | §2.4 | Before each stage exit; after each perf change |
| Failure injection | manual scripts | Redis stop, DB restart, process kill | Stage exits |
| Security | `pip-audit`, `gitleaks`, `check --deploy`, abuse scripts | §1.3 | CI + stage exits |

**Telling a real pass from "it survived briefly":**
- Metrics are flat over a long soak, not just green for the first minutes.
- p99 is within the SLO, not only p95.
- No error *trend* (a slowly rising 0.01% → 0.05% is a leak or a growing queue).
- Resources (connections, Redis memory, file descriptors) return to baseline after load stops.

---

## 3.4 Deployment, migrations, rollback

### Release sequence (every deploy)

1. CI green (tests, checks, audit).
2. Migrations are **backward-compatible with the currently running code** (expand only).
3. Run migrations.
4. Deploy new code (stage 1: restart; stage 2: rolling, one server at a time, graceful WS close).
5. Watch dashboards for 15 minutes: error rate, p95, reconnects.
6. On regression, **roll back the code** (previous image tag). Expand-only migrations don't need rolling back.

### Migration rules (memorise these; they prevent most outages caused by deploys)

| Change | Safe way |
|---|---|
| Add index on a big table | `AddIndexConcurrently` in a migration with `atomic = False` |
| Add column | Nullable or with a constant default (Postgres 11+ makes that instant); backfill in batches later |
| Make a column NOT NULL | Add `CHECK (col IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → then `SET NOT NULL` |
| Rename / drop column | Never in one step: add new → dual-write → backfill → switch reads → stop writes → drop in a later release |
| Any migration | `SET lock_timeout = '5s'` so a blocked `ALTER` fails fast instead of queueing every query behind it |

**Why `lock_timeout` matters:** an `ALTER TABLE` waits for a lock. While it waits, *every
other query on that table queues behind it*. One stuck migration becomes a full outage.
Failing fast and retrying later is safer.

### Feature flags and gradual rollout

- Stage 1: a settings-based flag is enough (for example `USE_CURSOR_PAGINATION`).
- Stage 2: per-user percentage flags (a hash of the user id) to canary risky reads
  (T-25 switch-over), comparing metrics between flag-on and flag-off groups.

### If a major migration fails

- **During expand:** drop the half-created object (`DROP INDEX CONCURRENTLY IF EXISTS …` for an invalid index) and retry.
- **During backfill:** it's resumable from a checkpoint; fix the bug, continue.
- **After switching reads:** flip the flag back.
- **After contract (data dropped):** only a restore brings it back. That's why contract waits a week and needs a fresh backup first.

---

## 3.5 Backup, disaster recovery and infrastructure cost

### Backup and DR by stage

| Stage | Backup | RPO / RTO (provisional) | Drill |
|---|---|---|---|
| 0 → 1 launch | Nightly logical dump off-site, or managed snapshots | 24 h / 4 h | Restore into a scratch DB before launch |
| 1 (1,000 online) | Managed PITR or WAL archiving | 1 h / 2 h | Monthly PITR restore to a timestamp |
| 2 (10,000 online) | PITR + standby in another zone | 5 min / 30–60 min | Quarterly failover under load; full-size restore timed |

- **Redis is not backed up for recovery purposes:** channel-layer and presence data
  is ephemeral, and throttles reset harmlessly. Recovery = start empty; clients reconnect
  (that's why T-09 matters).
- **Media (avatars):** object storage with versioning (stage 2).

### Cost-estimation methodology (no invented prices)

I don't know your provider, region or budget, and prices change, so this gives you the
**method** and the **inventory**. You fill in prices from the provider's calculator.

1. **Inventory per stage** (from the architecture sections):

   | Component | Stage 1 (1,000 online) | Stage 2 (10,000 online) |
   |---|---|---|
   | App compute | 1 VM (2–4 vCPU), 1–2 processes | 3+ servers/containers (HTTP + WS pools), count from the stress test |
   | Postgres | Managed with PITR, or on the VM | Managed primary + standby (≈ 2× DB cost) |
   | Redis | On the VM | Managed with replica |
   | Load balancer | — (reverse proxy on the VM) | 1 managed LB |
   | Object storage + CDN egress | — | Avatars |
   | Monitoring / errors | Free/low tiers | Paid tier (ingest-based) |
   | Backups | Storage GB-month | Included with PITR |
   | SMS (if OTP) | — | Per message, with a spend cap |
   | Load-test machines | 1 extra machine during tests | 2–4 machines during tests (hourly) |

2. **Separate fixed from usage-based:** VMs, DB instances and LB are fixed per month.
   Egress, storage growth, log ingest and SMS are usage-based (and the ones that surprise people).
3. **Unit cost KPI:** total monthly cost ÷ (peak online users / 1,000). Track it every month.
   If it rises as you grow, something is scaling worse than linearly.
4. **Storage projection:** measure average row size (`pg_total_relation_size / count`) ×
   messages/day × retention days. Do the same for backups.
5. **Very rough order of magnitude** (to sanity-check your calculation, not a quote):
   stage 1 tens to low hundreds of USD/month; stage 2 hundreds to low thousands
   (HA roughly doubles database cost), dominated by database, compute and egress.

**Cost controls:**
- Budget alerts at 50/80/100% of the monthly budget.
- Hard spend caps on SMS providers.
- Autoscaling max limits.
- Log retention limits and sampling.
- Rate limits on every endpoint that triggers paid work.
- Retention policy for messages and backups.

---

## 3.6 Readiness checklists

### Stage 0 done (ready for real users)
- [ ] T-01, T-02, T-03, T-04, T-05 (decision), T-06, T-08, T-09, T-11 done
- [ ] `check --deploy` clean; `gitleaks` clean; new secret key in use
- [ ] Abuse scripts: brute force, enumeration, message flood all rejected
- [ ] Baseline measured with the realistic profile from a second machine

### Stage 1 done (1,000 online)
- [ ] T-10, T-12, T-14 (restore drill done and timed)
- [ ] T-13, T-15, T-16, T-17, T-18 done with before/after numbers (T-22 only if needed)
- [ ] Real metrics for A1–A2 collected for ≥ 2 weeks; plan updated with them
- [ ] Load test 2,000 online from a separate machine: p95 ≤ 300 ms, p99 ≤ 1 s
- [ ] Reconnect storm at 2,000 online passes; 4 h soak at 1,000 online flat

### Stage 2 done (10,000 online, final target)
- [ ] T-21, T-23, T-24, T-26, T-27, T-30, T-31 done; T-25/T-32–T-35 only if their triggers fired
- [ ] Server kill, DB failover, Redis restart and rolling deploy, all under load, pass
- [ ] Load test 20,000 online from several generator machines; 8 h soak at 10,000 flat
- [ ] Runbooks written; SLO alerts live; retention policy agreed
- [ ] Cost per 1,000 online known; budget alerts and spend caps active
