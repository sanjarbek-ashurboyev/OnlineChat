# OnlineChat scaling plan

Repository-specific audit and staged plan for growing OnlineChat to **10,000 users
online at the same time**: now (~100 online) → 1,000 online → 10,000 online.
100,000+ online is out of scope.
Written 2026-10-09 against commit `3bd73a8`.
**2026-10-10:** `main` already contained later work (secrets from env, tests, CI). See the
[status update in the audit](01-audit.md#status-update--2026-10-10) for which findings are fixed.

## Executive summary

1. **The biggest problems today are not about scale.**
   - The Django `SECRET_KEY` is committed to a **public** GitHub repository. Because
     login tokens are signed with it, anyone can forge a login as any user (SEC-1).
   - Login, registration, messaging and user lookup by id have **no rate limits**
     (SEC-3 to SEC-5).
   - Messages that arrive during a reconnect **never appear** in the open chat (COR-1).
   - **These come first, at any traffic level.**
2. **Measured capacity:** one server process handled **100 online** with a heavy chat
   profile (about 6× more messages per user than a realistic one) and failed at 200.
   With a realistic profile it may hold roughly 600 online. That's an estimate, and
   measuring it is the first task.
3. **Why it fails:** all WebSocket database work in a process runs on **one thread**, and
   each database call opens a **new Postgres connection** (6.2 ms) to run a 0.2 ms query.
   One delivered and read message costs 7 such calls. The arithmetic matches the load test.
4. **The stages:**
   - **1,000 online:** one server. Deploy properly, add backups and monitoring, then the cheap
     efficiency fixes (connection pooling, fewer writes per message, a better chat list query).
   - **10,000 online (final target):** several servers behind a load balancer, separate HTTP
     and WebSocket processes, managed Postgres with a standby, managed Redis, graceful
     deploys. Still **one Django codebase and one primary Postgres**. No microservices,
     Kubernetes or sharding.
5. **The method matters more than the architecture:** measure, find the one bottleneck,
   fix the cheapest factor, measure again.

## Files

| File | Contents |
|---|---|
| [01-audit.md](01-audit.md) | What was inspected, architecture and request flows, every finding with file:line and evidence level |
| [02-plan.md](02-plan.md) | Unknowns, workload model, capacity model, test methodology, Stage 0, Stage 1 (1,000 online), Stage 2 (10,000 online), decisions with ADRs, exit criteria |
| [03-operations.md](03-operations.md) | Risk register, prioritised backlog (T-01…T-37), testing, deploy/migration/rollback, backup/DR, cost methodology, readiness checklists |
| [04-interview-guide.md](04-interview-guide.md) | Claims tracker (implemented vs measured vs designed), project story, interview Q&A at 3 levels, understanding checks |

## Start here (this week)

| Order | Task | Why first |
|---|---|---|
| 1 | **T-01** move `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS` to env, generate a new key | Critical, 2–4 h |
| 2 | **T-08** complete and pin `requirements.txt` | A fresh install currently fails |
| 3 | **T-11** finish tests + CI (mostly done in PR #5) | Every later change needs a safety net |
| 4 | **T-02**, **T-03**, **T-04** | Small, high-value fixes |
| 5 | **T-09** gap fetch + reconnect jitter | Makes every later deploy and failover safe |
| 6 | Baseline load test with the realistic profile, from a second machine | Know the real starting point before optimising |

## Evidence status

- **Measured:** load test result, Postgres connect vs query time, password hash cost,
  queries per endpoint, `EXPLAIN` of the chat list, `max_connections`, disconnect errors.
- **From library source:** thread model, channel layer limits, Daphne message size limit, SimpleJWT defaults.
- **Assumed (replace with real data):** chatting share and message rate (A1–A2), SLOs, RPO/RTO, costs.
- **Not inspected:** any production deployment (none found), real traffic.
