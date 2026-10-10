# Concepts

Read these in order the first time. Each one builds on the ones before it.

| # | Guide | Prerequisite | Short version |
|---|---|---|---|
| 1 | [HTTP and WebSockets](http-and-websockets.md) | Basic Django views | Letters vs a phone call |
| 2 | [Django Channels and Redis](django-channels-and-redis.md) | 1 | How one message reaches the other browser |
| 3 | [Authentication and JWT](authentication-and-jwt.md) | Basic Django auth | A signed ticket that proves who you are |
| 4 | [Configuration and secrets](configuration-and-secrets.md) | 3 | Keep secrets out of code; fail safe |
| 5 | [Dependency management](dependency-management.md) | pip, virtualenvs | Shopping list vs receipt |
| 6 | [Git branches, merge and rebase](git-branches-merge-rebase.md) | Basic git commit/push | Bookmarks and replaying work |
| 7 | [Performance and load testing](performance-and-load-testing.md) | 1, 2 | Measure, find the one bottleneck, fix the cheapest cause |
| 8 | [Testing and CI](testing-and-ci.md) | 2, 4 | Prove it works, automatically, on every change |
| 9 | [Rate limiting](rate-limiting.md) | 3 | A bouncer counting how often each person comes in |

Words used everywhere:

| Word | Meaning |
|---|---|
| **Latency** | How long one action takes, e.g. from "send" to the message appearing. |
| **p95** | Sort all latencies; p95 is the value 95% of them are faster than. It shows what the slowest users feel. |
| **Process / thread** | A process is a running program with its own memory. A thread is one line of work inside a process; a process can have several. |
| **Round trip** | A request out and its reply back, e.g. one query to Postgres. |
