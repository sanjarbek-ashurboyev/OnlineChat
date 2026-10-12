"""The load tester's socket bookkeeping (Codex audit M-21).

Needs aiohttp (loadtest/requirements.txt), which the app's CI doesn't install, so it is skipped there.
"""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless

HAS_AIOHTTP = importlib.util.find_spec('aiohttp') is not None
if HAS_AIOHTTP:
    import aiohttp

    sys.path.insert(0, str(Path(__file__).parent))  # run.py is a script: `from verdict import ...`
    from loadtest.run import SimUser, Stats


class BrokenSocket:
    """Delivers one message from the partner, then fails on the read receipt we send back."""

    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        yield SimpleNamespace(type=aiohttp.WSMsgType.TEXT,
                              data=json.dumps({'type': 'message', 'sender_id': 2, 'text': 'hi'}))

    async def send_str(self, data):
        raise ConnectionResetError

    async def close(self):
        self.closed = True


@skipUnless(HAS_AIOHTTP, 'needs aiohttp from loadtest/requirements.txt')
class ReaderTests(IsolatedAsyncioTestCase):
    async def test_a_reader_error_marks_the_socket_closed(self):
        run = SimpleNamespace(stats=Stats(), stopping=False, to_deliver={})
        user = SimUser(run, {'user_id': 1, 'chat_id': 1, 'token': 't'}, active=True)
        user.ws = BrokenSocket()
        sibling = asyncio.create_task(asyncio.sleep(60))  # stands in for the ping/poll/send loops
        user.tasks = [sibling]

        with self.assertRaises(ConnectionResetError):
            await user.read()
        await asyncio.sleep(0)

        self.assertTrue(user.closed)            # no longer counted as connected
        self.assertEqual(run.stats.drops, 1)
        self.assertTrue(user.ws.closed)
        self.assertTrue(sibling.cancelled())    # nothing keeps using the dead socket


class RecordingSocket:
    """Delivers one message from the partner, then ends; keeps what we sent."""

    def __init__(self):
        self.sent = []

    async def __aiter__(self):
        yield SimpleNamespace(type=aiohttp.WSMsgType.TEXT,
                              data=json.dumps({'type': 'message', 'id': 41, 'sender_id': 2, 'text': 'hi'}))

    async def send_str(self, data):
        self.sent.append(json.loads(data))

    async def close(self):
        pass


@skipUnless(HAS_AIOHTTP, 'needs aiohttp from loadtest/requirements.txt')
class ReadReceiptTests(IsolatedAsyncioTestCase):
    async def test_a_read_receipt_names_the_message_it_read(self):
        # The consumer requires up_to (decision 008) and answers a receipt without one with an
        # error frame, which the tester counted as a server error.
        run = SimpleNamespace(stats=Stats(), stopping=True, to_deliver={})
        user = SimUser(run, {'user_id': 1, 'chat_id': 7, 'token': 't'}, active=True)
        user.ws = RecordingSocket()
        user.tasks = []

        await user.read()

        self.assertEqual(user.ws.sent, [{'action': 'read', 'chat_id': 7, 'up_to': 41}])
