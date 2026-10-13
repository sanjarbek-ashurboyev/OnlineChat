# Health checks: liveness and readiness

## 1. Simple definition
A **health check** is a URL that a load balancer (or Docker, or Kubernetes) calls every few seconds to ask a
server "can you work?". There are two questions, and they're different:
- **Liveness** (`/healthz`): "is the process running at all?" If not, restart it.
- **Readiness** (`/readyz`): "can it serve requests *right now*?" If not, stop sending it traffic, but don't
  restart it.

## 2. Why it exists
With two or more app processes behind a load balancer, one of them can lose its database or Redis connection
while the others are fine. Without a readiness check the balancer keeps sending users there, and they get errors.
With one, it routes around the broken process until it recovers.

## 3. How it works, step by step
1. The balancer calls `GET /readyz` every few seconds, usually over plain HTTP, straight to the app.
2. The app tries each thing it can't work without: here, one `SELECT 1` on Postgres and one `PING` to Redis.
3. All answered → **200**. Any failed → **503** (Service Unavailable).
4. After a few 503s in a row the balancer takes the process out of rotation. After a few 200s it puts it back.

## 4. Small example
```
$ curl -i http://localhost:8002/readyz
HTTP/1.1 200 OK
{"database": "ok", "redis": "ok"}

# Redis pointed at a port nobody listens on:
HTTP/1.1 503 Service Unavailable
{"database": "ok", "redis": "error"}
```

## 5. In our project
- `root/health.py` `readyz()`, at `/readyz` (not under `/api/v1/`, and not in the API schema). Added in session 031.
- One Redis `PING` is enough: the channel layer, the cache and presence all live on the same Redis server.
- The answer says *which* check failed, never *why*. The exception goes to the log
  (`readyz: Redis check failed` + traceback), because error messages can contain hosts, ports or usernames.
- `SECURE_REDIRECT_EXEMPT = [r'^readyz$']` in `root/settings.py`: in production every plain-HTTP request is
  redirected to HTTPS (301), and a balancer would read a 301 as "down".
- No `/healthz` yet. Daphne answering at all already proves the process is alive.

## 6. Alternatives
- **One `/health` for both questions.** Common, but then a Redis outage makes the orchestrator *restart* healthy
  processes, which can't fix Redis and adds a reconnect storm.
- **Deep checks** (run a real query on a real table, send through the channel layer). More realistic, but slower and
  heavier on every probe.
- **No endpoint:** the balancer just checks the TCP port. It can't tell a process that has lost its database.

## 7. Common mistakes
- **Restarting on readiness failures.** If the database is down, restarting every app process helps nothing.
- **Leaking details**: returning the exception text (`could not connect to server at 10.0.3.7:5432`).
- **A check that hangs.** If Redis doesn't answer at all (no "connection refused", just silence), the probe waits.
  Set the balancer's probe timeout shorter than its interval.
- **Forgetting the redirect, the allowed hosts or authentication.** A probe that gets 301, 400 or 401 looks like a dead server.
  Ours is exempt from the redirect and needs no token. **Not handled yet:** a balancer that sends its own IP as the
  `Host` header gets a 400 unless that IP is in `DJANGO_ALLOWED_HOSTS` (T-10).

## 8. When to use it
As soon as more than one process serves traffic, or something restarts processes automatically (Docker
`healthcheck`, Kubernetes, a cloud load balancer). For one process on one machine, it's mostly a quick way to ask
"is everything connected?" by hand.
