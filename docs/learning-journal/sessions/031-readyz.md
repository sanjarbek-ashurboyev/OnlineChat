# 031 · `/readyz`: a process says whether it can serve

- **Date:** 2026-10-13 · **Phase:** Stage 0 → Stage 1
- **Task:** T-21 (partly) / T-12 step 3 ([backlog](../../scaling/03-operations.md)) · **Branch:** `t-21-readyz`, stacked on
  `t-07-refresh-rotation-logout` (PR #40)
- **Files:** `root/health.py` (new), `root/urls.py`, `root/settings.py`, `root/test_health.py` (new), docs
- **Objective:** a load balancer can tell a process that lost Postgres or Redis from a healthy one.

## What was done
1. **Tests first** (`root/test_health.py`, 5 tests): 200 with both up; 503 naming Redis; 503 naming the database;
   no token needed; a plain-HTTP probe isn't redirected while other paths still are. All 5 failed (no endpoint).
2. **Code:** `readyz()` in `root/health.py` runs `SELECT 1` and a Redis `PING`, logs any failure, and answers
   200 or 503 with `{"database": "ok"|"error", "redis": "ok"|"error"}`. Route: `/readyz`.
   `SECURE_REDIRECT_EXEMPT = [r'^readyz$']`.
3. **One test still failed** with a 301: see [P-35](../problems-and-solutions.md#p-35--a-production-only-setting-was-missing-from-the-local-tests).
   Moved the exemption out of `if not DEBUG:`; now it passes with `DEBUG` on and off.
4. **Real stack:** Daphne on port 8002 in production mode (`DJANGO_DEBUG=False`, HTTPS redirect on):

   | Case | `/readyz` | `/api/v1/chats/` | Log |
   |---|---|---|---|
   | Both up | 200 `{"database": "ok", "redis": "ok"}` (0.04 s) | 301 | nothing |
   | `REDIS_PORT=6390` (nothing listens) | 503 `{"database": "ok", "redis": "error"}` | 301 | `readyz: Redis check failed` |
   | `DB_PORT=5440` (nothing listens) | 503 `{"database": "error", "redis": "ok"}` | 301 | `readyz: database check failed` |

   Daphne was stopped after each case (port 8002 free afterwards).
5. **Results:** `make test` **162 run, OK (15 skipped)**; real Postgres + Redis with `REQUIRE_BROWSER_TESTS=True`
   **197 OK**; Ruff clean.

**Not done:**
- T-21's acceptance ("stop Redis under load: REST still answers, 5xx < 1%") isn't measured. T-21 stays *Partial*.
- No `/healthz` (liveness). Daphne answering at all already says the process is alive.
- A Redis that doesn't answer at all (silence, not "connection refused") would make the probe wait. The balancer's
  probe timeout covers it (T-10).
- A balancer that sends its own IP as `Host` would get a 400 from `ALLOWED_HOSTS`. That's T-10's setup.

## Concepts
New guide: [health checks: liveness and readiness](../concepts/health-checks.md).
- **Readiness:** "can this process serve *now*?" → stop sending it traffic if not.
- **Liveness:** "is it running at all?" → restart it if not.
- Mixing them up means restarting healthy processes because Redis is down, which fixes nothing.

## Walkthrough: `root/health.py`
```python
@require_safe
def readyz(request):
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception:
        logger.exception('readyz: database check failed')
        checks['database'] = 'error'
    ...
    ready = all(value == 'ok' for value in checks.values())
    return JsonResponse(checks, status=200 if ready else 503)
```
- `@require_safe`: GET and HEAD only. Balancers often use HEAD.
- `except Exception` is deliberate here: *any* failure means "not ready", and the check must still answer.
  `logger.exception` keeps the traceback in the log, never in the response.
- A plain Django view, not a DRF one: no authentication, no throttle, and it stays out of the API schema.

## Problems
- [P-35](../problems-and-solutions.md#p-35--a-production-only-setting-was-missing-from-the-local-tests): a setting
  inside `if not DEBUG:` didn't exist in local tests, because the local `.env` turns DEBUG on. New GOTCHA line.

## Decisions
- Say *which* check failed, never *why* (no hosts or ports in a public answer).
- One Redis `PING`, not one per use (channel layer, cache, presence): they're one server.

## What I should remember
- Readiness ≠ liveness. A 503 from `/readyz` means "route around me", not "restart me".
- Local tests run with `.env`'s `DEBUG=True`; CI with DEBUG off. Test production-only settings both ways.
- To fake an outage, point the app at a port nobody listens on (P-26), and check with `lsof` first.

## Review questions
1. Why is `/readyz` exempt from the HTTPS redirect?
2. Why does the answer say `"redis": "error"` and not the exception's message?
3. Redis goes down. Should Docker restart the app processes? Why or why not?
4. The redirect test passed in CI but failed locally (before the fix). Why?
5. Why is one `PING` enough, when three different parts of the app use Redis?

<details><summary>Answer key</summary>

1. Balancers probe the app directly, over plain HTTP. In production every plain-HTTP request gets a 301, and a 301
   doesn't count as healthy, so every process would look down.
2. Exception messages can contain hosts, ports and usernames. The endpoint is public; the log isn't.
3. No. Restarting can't fix Redis, and every restarted process then reconnects at once. Take them out of rotation
   (readiness) and let them recover when Redis is back.
4. `root/settings_test.py` imports `root/settings.py`, which loads `.env`. Locally `DJANGO_DEBUG=True`, so the
   `if not DEBUG:` block holding the exemption never ran. CI has no `.env`, so DEBUG is off and the block runs.
5. The channel layer (db 0), the cache (db 1) and presence (db 2) are three databases on one Redis server. If one
   answers, the server is up.
</details>

## Next steps
- T-13 (connection pool), with a load test before and after.
- T-21's outage test under load, when T-12's load-test scenarios exist.
