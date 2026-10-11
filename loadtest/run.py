#!/usr/bin/env python
"""Step load test: how many people can be online before the app slows down.

Each simulated user behaves like the browser client in assets/app.js: one
inbox WebSocket, a ping every 30s, a chat list reload every 45s, and (for the
"active" share of users) messages sent to their paired chat. Users are added
in steps; after each step the test holds the load and reports latencies.

    python manage.py loadtest_seed --users 2000
    python manage.py runserver            # or daphne root.asgi:application
    python loadtest/run.py --steps 100,250,500,1000,2000

Run the client on a different machine than the server if you can: on one
laptop the two compete for CPU and the numbers come out pessimistic.
"""

import argparse
import asyncio
import json
import random
import resource
import sys
import time
import uuid
from dataclasses import dataclass, field

import aiohttp
from verdict import pct, problems


@dataclass
class Stats:
    connect_ms: list = field(default_factory=list)
    connect_errors: int = 0
    drops: int = 0            # sockets closed by the server mid-test
    message_ms: list = field(default_factory=list)
    delivery_ms: list = field(default_factory=list)   # send -> arrival at the recipient
    ping_ms: list = field(default_factory=list)
    poll_ms: list = field(default_factory=list)
    sent: int = 0
    lost: int = 0             # no echo within --message-timeout
    to_online: int = 0        # sent while the recipient was connected
    undelivered: int = 0      # of those, never reached the recipient
    poll_errors: int = 0
    server_errors: int = 0    # {"type": "error"} frames from the consumer

    def reset_traffic(self):
        """Forget ramp-up traffic so a step reports only its steady state."""
        self.message_ms, self.delivery_ms, self.ping_ms, self.poll_ms = [], [], [], []
        self.sent = self.lost = self.to_online = self.undelivered = 0
        self.poll_errors = self.server_errors = 0


class SimUser:
    def __init__(self, run, info, active):
        self.run = run
        self.user_id = info['user_id']
        self.chat_id = info['chat_id']
        self.token = info['token']
        self.active = active
        self.ws = None
        self.tasks = []
        self.pending = {}      # message text -> send time
        self.ping_sent = None
        self.closed = False

    @property
    def stats(self):
        # Looked up each time: the run swaps in a fresh Stats per step.
        return self.run.stats

    async def start(self):
        args = self.run.args
        started = time.perf_counter()
        try:
            self.ws = await asyncio.wait_for(
                self.run.session.ws_connect(
                    f'{self.run.ws_base}/ws/inbox/?token={self.token}',
                    # AllowedHostsOriginValidator rejects sockets with no Origin.
                    headers={'Origin': args.url},
                ),
                timeout=args.connect_timeout,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            self.stats.connect_errors += 1
            return False
        self.stats.connect_ms.append((time.perf_counter() - started) * 1000)
        self.run.by_chat.setdefault(self.chat_id, []).append(self)

        self.tasks = [asyncio.create_task(self.read()),
                      asyncio.create_task(self.ping_loop()),
                      asyncio.create_task(self.poll_loop())]
        if self.active:
            self.tasks.append(asyncio.create_task(self.send_loop()))
        return True

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        if self.ws is not None:
            await self.ws.close()

    async def read(self):
        try:
            async for frame in self.ws:
                if frame.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(frame.data)
                kind = data.get('type')
                now = time.perf_counter()
                if kind == 'pong' and self.ping_sent is not None:
                    self.stats.ping_ms.append((now - self.ping_sent) * 1000)
                    self.ping_sent = None
                elif kind == 'message':
                    if data.get('sender_id') == self.user_id:
                        sent = self.pending.pop(data.get('text'), None)
                        if sent is not None:
                            self.stats.message_ms.append((now - sent) * 1000)
                        continue
                    sent = self.run.to_deliver.pop(data.get('text'), None)
                    if sent is not None:
                        self.stats.delivery_ms.append((now - sent) * 1000)
                    if self.active:
                        # The open chat marks incoming messages read, like the browser does.
                        await self.ws.send_str(json.dumps({'action': 'read', 'chat_id': self.chat_id}))
                elif kind == 'error':
                    self.stats.server_errors += 1
        finally:
            # Also when handling a frame raised: a dead socket must not count as connected,
            # and the ping/poll/send loops must not keep using it.
            self.closed = True
            if not self.run.stopping:
                self.stats.drops += 1
            for task in self.tasks:
                if task is not asyncio.current_task():
                    task.cancel()
            await self.ws.close()

    def partner_online(self):
        return any(u is not self and not u.closed for u in self.run.by_chat[self.chat_id])

    async def ping_loop(self):
        interval = self.run.args.ping
        await asyncio.sleep(random.uniform(0, interval))
        while True:
            self.ping_sent = time.perf_counter()
            await self.ws.send_str('{"action": "ping"}')
            await asyncio.sleep(interval)

    async def poll_loop(self):
        interval = self.run.args.poll
        url = f'{self.run.args.url}/api/v1/chats/'
        headers = {'Authorization': f'Bearer {self.token}'}
        await asyncio.sleep(random.uniform(0, interval))
        while True:
            started = time.perf_counter()
            try:
                async with self.run.session.get(url, headers=headers,
                                                timeout=self.run.http_timeout) as resp:
                    await resp.read()
                    ok = resp.status == 200
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                ok = False
            if ok:
                self.stats.poll_ms.append((time.perf_counter() - started) * 1000)
            else:
                self.stats.poll_errors += 1
            await asyncio.sleep(interval)

    async def send_loop(self):
        mean_gap = 60 / self.run.args.msg_rate
        while True:
            await asyncio.sleep(random.expovariate(1 / mean_gap))
            if self.run.paused:
                continue
            text = f'lt {uuid.uuid4().hex}'
            self.pending[text] = time.perf_counter()
            self.stats.sent += 1
            if self.partner_online():
                self.run.to_deliver[text] = self.pending[text]
                self.stats.to_online += 1
            await self.ws.send_str(json.dumps(
                {'action': 'message', 'chat_id': self.chat_id, 'text': text}))


class Run:
    def __init__(self, args, session, accounts):
        self.args = args
        self.session = session
        self.accounts = accounts
        self.ws_base = args.url.replace('http', 'ws', 1)
        self.http_timeout = aiohttp.ClientTimeout(total=args.http_timeout)
        self.users = []
        self.by_chat = {}          # chat id -> connected SimUsers, to find the recipient
        self.to_deliver = {}       # message text -> send time, until the recipient gets it
        self.attempted = 0
        self.stats = Stats()
        self.stopping = False
        self.paused = False        # no new messages while a step's last ones are counted

    async def ramp_to(self, target):
        gap = 1 / self.args.connect_rate
        pending = []
        for info in self.accounts[self.attempted:target]:
            user = SimUser(self, info, active=random.random() < self.args.active)
            pending.append(asyncio.create_task(self._start(user)))
            await asyncio.sleep(gap)
        self.attempted = max(self.attempted, target)
        await asyncio.gather(*pending)

    async def _start(self, user):
        if await user.start():
            self.users.append(user)

    def forget_in_flight(self):
        """Drop messages sent before the step started; their answers aren't this step's."""
        for user in self.users:
            user.pending.clear()
        self.to_deliver.clear()

    async def drain(self):
        """Stop sending, then wait for in-flight messages. Whatever is still missing is lost."""
        self.paused = True
        deadline = time.perf_counter() + self.args.message_timeout
        while time.perf_counter() < deadline and (
                self.to_deliver or any(u.pending for u in self.users)):
            await asyncio.sleep(0.1)
        self.stats.lost += sum(len(u.pending) for u in self.users)
        self.stats.undelivered += len(self.to_deliver)
        self.forget_in_flight()

    async def stop(self):
        self.stopping = True
        await asyncio.gather(*(u.stop() for u in self.users), return_exceptions=True)


def summarize(run, target):
    s = run.stats
    # Count open sockets, not "connected minus this step's drops": earlier drops stay dropped.
    connected = sum(1 for u in run.users if not u.closed)
    row = {
        'users': target,
        'connected': connected,
        'connect_p95_ms': pct(s.connect_ms, 95),
        'messages_sent': s.sent,
        'message_p50_ms': pct(s.message_ms, 50),
        'message_p95_ms': pct(s.message_ms, 95),
        'message_p99_ms': pct(s.message_ms, 99),
        'messages_to_online': s.to_online,
        'delivery_p95_ms': pct(s.delivery_ms, 95),
        'ping_p95_ms': pct(s.ping_ms, 95),
        'polls': len(s.poll_ms),
        'poll_p95_ms': pct(s.poll_ms, 95),
        'connect_errors': s.connect_errors,
        'drops': s.drops,
        'lost_messages': s.lost,
        'undelivered': s.undelivered,
        'poll_errors': s.poll_errors,
        'server_errors': s.server_errors,
    }
    row['problems'] = problems(row, run.args)
    row['healthy'] = not row['problems']
    return row


def fmt(value):
    return '-' if value is None else f'{value:.0f}'


def print_row(row):
    verdict = 'OK' if row['healthy'] else 'FAIL: ' + '; '.join(row['problems'])
    print(f'{row["users"]:>6} {row["connected"]:>6} {row["messages_sent"]:>6} '
          f'{fmt(row["message_p50_ms"]):>6} {fmt(row["message_p95_ms"]):>6} '
          f'{fmt(row["message_p99_ms"]):>6} {fmt(row["delivery_p95_ms"]):>6} {fmt(row["ping_p95_ms"]):>6} '
          f'{fmt(row["poll_p95_ms"]):>6}  {verdict}', flush=True)


def raise_fd_limit():
    """One socket per user plus HTTP connections; macOS defaults to 256 files."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    for wanted in (65536, 10240):
        target = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
        if target <= soft:
            return
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            return
        except (ValueError, OSError):
            continue


async def main(args):
    raise_fd_limit()
    with open(args.tokens) as fh:
        accounts = json.load(fh)
    steps = sorted({int(n) for n in args.steps.split(',')})
    if steps[-1] > len(accounts):
        sys.exit(f'Largest step is {steps[-1]} users but {args.tokens} has {len(accounts)}. '
                 f'Run: python manage.py loadtest_seed --users {steps[-1]}')

    print(f'Target {args.url}  steps {steps}  hold {args.hold:.0f}s  '
          f'{args.active:.0%} active at {args.msg_rate:g}/min\n')
    print(f'{"users":>6} {"online":>6} {"sent":>6} {"msg50":>6} {"msg95":>6} '
          f'{"msg99":>6} {"recv95":>6} {"ping95":>6} {"list95":>6}  (latencies in ms)')

    results = []
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        run = Run(args, session, accounts)
        try:
            for target in steps:
                await run.ramp_to(target)
                run.stats.reset_traffic()
                run.forget_in_flight()
                run.paused = False
                await asyncio.sleep(args.hold)
                await run.drain()
                row = summarize(run, target)
                results.append(row)
                print_row(row)
                if not row['healthy'] and not args.keep_going:
                    break
                run.stats = Stats()
        finally:
            await run.stop()

    healthy = [r['users'] for r in results if r['healthy']]
    print()
    if healthy:
        print(f'Highest healthy step: {max(healthy)} users online at once.')
    else:
        print('No step was healthy; start with a smaller first step.')
    if results and results[-1]['healthy']:
        print('Every step passed, so the real limit is higher. Add bigger steps.')

    if args.json:
        with open(args.json, 'w') as fh:
            json.dump({'args': vars(args), 'results': results}, fh, indent=2)
        print(f'Results written to {args.json}')


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--url', default='http://localhost:8000')
    p.add_argument('--tokens', default='loadtest/tokens.json')
    p.add_argument('--steps', default='50,100,250,500,1000',
                   help='Comma-separated online user counts to test, smallest first.')
    p.add_argument('--hold', type=float, default=60, help='Seconds to measure at each step.')
    p.add_argument('--connect-rate', type=float, default=50, help='New sockets per second.')
    p.add_argument('--active', type=float, default=0.2,
                   help='Share of users who send messages (0-1).')
    p.add_argument('--msg-rate', type=float, default=4,
                   help='Messages per minute per active user.')
    p.add_argument('--ping', type=float, default=30, help='Seconds between pings (app.js PING_MS).')
    p.add_argument('--poll', type=float, default=45, help='Seconds between chat list reloads.')
    # Defaults are the targets in docs/scaling/02-plan.md.
    p.add_argument('--max-message-ms', type=float, default=300,
                   help='Message (echo and delivery) p95 above this fails the step.')
    p.add_argument('--max-message-p99-ms', type=float, default=1000,
                   help='Message p99 above this fails the step.')
    p.add_argument('--max-poll-ms', type=float, default=300,
                   help='Chat list p95 above this fails the step.')
    p.add_argument('--max-error-rate', type=float, default=0.001,
                   help='Failed connects, lost messages or failed requests must stay under this share.')
    p.add_argument('--message-timeout', type=float, default=10,
                   help='After each step, seconds to wait for in-flight messages before calling them lost.')
    p.add_argument('--connect-timeout', type=float, default=15)
    p.add_argument('--http-timeout', type=float, default=15)
    p.add_argument('--keep-going', action='store_true', help="Don't stop at the first failing step.")
    p.add_argument('--json', help='Also write results to this file.')
    return p.parse_args()


if __name__ == '__main__':
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        pass
