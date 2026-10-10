# 014 · Baseline load test: realistic profile, second machine, and what actually limited it

- **Date:** 2026-10-11 · **Phase:** Stage 0 (last item)
- **Task:** baseline load test ([plan §2.4](../../scaling/02-plan.md), README step 6) · **Branch:** `baseline-load-test` (docs only)
- **Code under test:** `main` at `ac84b47` (everything up to the presence-leak fix, PR #22)
- **Objective:** know the app's real starting point with a realistic workload before changing anything for Stage 1.

## Setup
| What | Value |
|---|---|
| Server | This Mac (Apple M4, 10 cores). **One Daphne process**: `daphne -b 0.0.0.0 -p 8001 root.asgi:application` |
| Settings | Production-like: `DJANGO_DEBUG=False`, `DJANGO_SSL_REDIRECT=False` (plain HTTP on the local network), set in the shell only. `.env` unchanged |
| Data | Docker Postgres 17, Homebrew Redis 8.10. `loadtest_seed --users 2000 --token-hours 4`: 2,000 users, 1,000 chats, 20,000 messages |
| Profile | Realistic: 20% of users active at 4 messages/min each, a ping every 30 s, the chat list reloaded every 45 s. Each step held 60 s |
| Pass rule | Message p95 ≤ 500 ms, chat list p95 ≤ 1,000 ms, no lost messages or failed connects |
| Generator | Run 1: **a second Mac** (`uv run --python 3.13`), both Macs on an **iPhone Personal Hotspot**. Runs 2–3: the server Mac itself |
| Server-side recording | Every 5 s: Daphne CPU and memory, its open TCP sockets, Postgres connections, Redis clients |

## Results

**Run 1: second Mac, over the hotspot**
| Users | Sent | msg p50 | msg p95 | msg p99 | ping p95 | list p95 | Result |
|---:|---:|---:|---:|---:|---:|---:|---|
| 100 | 68 | 123 | 296 | 346 | 366 | 237 | OK |
| 200 | 181 | 114 | 250 | 430 | 228 | 220 | OK |
| 300 | 231 | 178 | **616** | 763 | 468 | 507 | **FAIL** |

**Run 2: the same steps from the server Mac (no network in between)**
| Users | Sent | msg p50 | msg p95 | msg p99 | ping p95 | list p95 | Result |
|---:|---:|---:|---:|---:|---:|---:|---|
| 100 | 68 | 64 | 78 | 96 | 31 | 40 | OK |
| 200 | 177 | 59 | 95 | 114 | 42 | 38 | OK |
| 300 | 218 | 58 | **90** | 126 | 44 | 38 | OK |

**Run 3: stepping up from the server Mac, to find the server's own limit**
| Users | Sent | msg p50 | msg p95 | msg p99 | ping p95 | list p95 | Result |
|---:|---:|---:|---:|---:|---:|---:|---|
| 500 | 358 | 54 | 111 | 125 | 47 | 36 | OK |
| 750 | 578 | 55 | 122 | 180 | 51 | 32 | OK |
| 1,000 | 803 | **711** | **6,423** | 9,567 | 2,312 | **39** | **FAIL** |

**Server during the runs** (averages of the 5 s samples, grouped by open sockets on Daphne)
| Open sockets | Daphne CPU avg (max), % of one core |
|---|---|
| 250–499 | 19% (46%) |
| 500–749 | 26% (42%) |
| 750–999 | 37% (59%) |
| 1,000+ | 53% (59%) |

Memory grew from 76 to 149 MB. Postgres connections were 1–4 at any sample, because each call opens and closes its own.

## What the numbers say

1. **The second-machine result (200 healthy, 300 failing) measured the hotspot, not the server**
   ([P-19](../problems-and-solutions.md#p-19--the-second-machine-baseline-measured-the-hotspot-not-the-server)).
   Even at 100 users, ping p95 was 366 ms over the hotspot versus 31 ms locally. The same 300-user step passed
   locally with message p95 90 ms, even though the generator then shared the CPU.
2. **The server's own ceiling is between 750 and 1,000 users online, on one process.** It's a cliff, not a slope:
   message p50 went from 55 to 711 ms.
3. **The bottleneck is the WebSocket side, and not the CPU** (*strongly supported hypothesis*):
   - The chat list (REST) stayed at 39 ms while messages collapsed. REST requests each get their own thread, but all
     WebSocket database and Redis calls queue on **one** thread per process (PERF-1).
   - Daphne used only about 55% of one core at 1,000 users. A thread that waits on new database connections
     (about 6 ms each, PERF-2) is busy without using CPU.
   - The audit's numbers predict the cliff. Rough estimate, not measured on the thread itself: a ping costs about
     2 trips (≈ 7 ms), a message about 7 trips (≈ 45 ms, PERF-3). Per second at N users, that's
     N/30 × 7 ms + N × 0.2 × 4/60 × 45 ms ≈ **0.83 ms × N**, so the one thread is busy about **62% at 750, 83% at 1,000**,
     and fully at about 1,200. Queues explode as utilisation nears 100%
     ([concept](../concepts/performance-and-load-testing.md)).
4. **The Redis connection pool overflows on bursts of disconnects** (P-13 again): 169, 116 and 612
   `MaxConnectionsError`s, all in the second each test ended, when 300 to 1,000 sockets closed at once. The T-02 fix
   held: each failure was logged, and the users were still marked offline. One message send at the end of the
   1,000-user test also hit it and crashed one consumer. The message was already saved, so T-09's gap fetch recovers it.

**Compared with session 001** (100 healthy, 200 failing): that profile sent about 6× more messages per user and the
generator shared the machine. Today's numbers aren't directly comparable. They're the new baseline.

## Not done
- **A clean second-machine number.** Re-run Run 1 with both machines on a normal Wi-Fi or wired network. Until then,
  the Stage 0 checkbox stays open, with a note.
- `--json` files: the second machine's command got split by the shell, and the local runs didn't save JSON. The
  tables above are copied from the terminal output, and the server samples are summarised from the recorder's CSV
  (not committed: it lived in my scratchpad).
- Soak test (hours at 1× peak), reconnect storm, HTTP-only test: later, per §2.4.

## Concepts I learned

### Confounder
- **Simple definition:** a second thing that could explain your result. Here: "the server is slow" vs "the network
  is slow". Both predict a 616 ms p95.
- **How to separate them:** change one thing and keep everything else. Same server, same profile, same 300 users,
  **no network**: the p95 fell from 616 to 90 ms. So the network was the difference.

### A cliff, not a slope
At 750 users the median message took 55 ms, and at 1,000 it took 711 ms. That's what a single queue looks like near
full utilisation: waiting time grows like 1 / (1 − utilisation), so going from 62% to 83% busy doesn't add 30%,
it multiplies the wait.

### "Not CPU-bound" doesn't mean "not busy"
A thread waiting for Postgres to accept a new connection uses no CPU, but it can't serve anyone else. CPU graphs
alone would have said "plenty of room".

## What I should remember
- A load test also measures the network. Check it before blaming the server.
- Look at *which* numbers fail. REST fine plus WebSocket collapsing points at the WebSocket path.
- One process tops out between 750 and 1,000 online users today. The fixes are already planned: pooled connections
  (PERF-2), fewer trips per message and ping (PERF-3, T-15), then more processes.
- Save every run with `--json`, the commit and the config. Type long commands on one line.

## Review questions
1. Why couldn't the second-machine result be used as the server's limit?
2. What single experiment separated "network" from "server", and why does it work?
3. REST stayed at 39 ms while messages took seconds. What does that tell you about where the bottleneck is?
4. Daphne was at about 55% CPU when it failed. How can it be overloaded?
5. Using the estimate 0.83 ms × N, at roughly how many users does one process reach 100%? What would halving the
   time per database call do?
6. Why did all the `MaxConnectionsError`s happen in the same second?

<details><summary>Answer key</summary>

1. Ping, the lightest frame, already had a p95 of 366 ms at 100 users over the hotspot, versus 31 ms locally. The
   tail latency came from the network path, so the step failed for reasons outside the server.
2. The same 300-user step, same server and profile, run from the server machine with no network in between. Only
   the network changed, and p95 fell from 616 to 90 ms, so the network was the cause. (The local run is even
   *disadvantaged*, because the generator steals CPU, which makes the conclusion stronger.)
3. HTTP requests each get their own thread, while WebSocket work shares one thread per process. Only the shared
   path collapsed, which points at that single thread (PERF-1), not at Postgres or the CPU in general.
4. The thread spends its time *waiting*, mostly on opening a new Postgres connection for every call (PERF-2). Waiting
   uses no CPU, but the thread can't serve the queue while it waits.
5. About 1,200 users (1,000 ms ÷ 0.83 ms). Halving the time per call roughly halves the cost per user, so the same
   thread would reach 100% at about 2,400 users. That's why connection pooling comes first in Stage 1.
6. Each test ends by closing all its sockets at once. Every `disconnect()` calls `group_discard`, each needing a Redis
   connection, and the pool allows 100 per process, so the burst overflows it (P-13).
</details>

## Next steps
- Re-run the second-machine baseline on a normal network, saving `--json` (one-line command).
- Stage 1, cheapest fix first: connection pooling (PERF-2), then fewer DB trips per ping and message (T-15, PERF-3),
  then the Redis pool size, then more processes. Re-run this exact test after each change to measure what it bought.
