"""The real app.js in a real browser (Chromium, through Playwright) against a live server.

The server runs in a separate process (Daphne), so it needs a database and channel layer that
two processes can share: Postgres and Redis. Runs in the CI job test-postgres-redis; skipped on
the SQLite settings. Locally: docker compose up -d, playwright install chromium, then
python manage.py test chats.test_browser.
"""
import json
import multiprocessing
import os
import re
import unittest
from datetime import timedelta

from channels.testing import ChannelsLiveServerTestCase
from django.db import connection
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from chats.models import Block, Chat, Message
from test_helpers import PASSWORD, make_user, phone, token_for

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class BrowserTestCase(ChannelsLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor == 'sqlite':
            raise unittest.SkipTest('needs Postgres and Redis')
        if sync_playwright is None:
            raise unittest.SkipTest('needs playwright')
        # Playwright's sync API runs an event loop in this thread, which makes Django refuse
        # ORM calls here. The calls are ours and synchronous, so it's safe (Django's docs say so).
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        # Start the server as a fresh process (macOS's default). Under Linux's default, fork, the
        # page's socket never connected (P-22); the copy inherits this process's state.
        cls._start_method = multiprocessing.get_start_method(allow_none=True)
        multiprocessing.set_start_method('spawn', force=True)
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as error:  # browser not downloaded
            cls.playwright.stop()
            super().tearDownClass()
            multiprocessing.set_start_method(cls._start_method, force=True)
            raise unittest.SkipTest(f'needs Chromium: {error}') from error

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
        multiprocessing.set_start_method(cls._start_method, force=True)

    def setUp(self):
        super().setUp()
        self.me, self.friend = make_user(1), make_user(2)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.friend)

    def open_app(self, user=None, refresh=False, setup=None, connected=True):
        """Load the app signed in as `user`, the way a returning visitor arrives.

        refresh: also store a refresh token. setup(page): runs before the page loads (routes, clock).
        """
        user = user or self.me
        context = self.browser.new_context()
        self.addCleanup(context.close)
        script = f"localStorage.setItem('access', '{token_for(user)}');"
        if refresh:
            script += f"localStorage.setItem('refresh', '{RefreshToken.for_user(user)}');"
        context.add_init_script(script)
        page = context.new_page()
        if setup:
            setup(page)
        page.goto(self.live_server_url)
        if connected:
            expect(page.locator('#conn-state.is-open')).to_be_attached()
        return page

    def wait_until(self, page, condition, timeout=5):
        """Poll a Python-side condition (a held route arriving, a row in the database)."""
        for _ in range(int(timeout / 0.05)):
            if condition():
                return
            page.wait_for_timeout(50)
        self.fail('condition never became true')

    def say(self, chat, sender, *texts):
        for text in texts:
            Message.objects.create(chat=chat, sender=sender, text=text)

    def rows(self, page):
        return page.locator('#message-rows .bubble').evaluate_all(
            'bubbles => bubbles.map(b => b.firstChild.textContent)')


class SwitchingChatsTests(BrowserTestCase):
    def test_a_slow_answer_for_the_previous_chat_is_ignored(self):
        # Codex #3: open A, then B before A's history arrives.
        third = make_user(3)
        other_chat, _ = Chat.objects.get_or_create_chat(self.me, third)
        self.say(self.chat, self.friend, 'from A')
        self.say(other_chat, third, 'from B')

        page = self.open_app()
        held = []
        page.route(re.compile(rf'/api/v1/chats/{self.chat.id}/messages/(\?page=1)?$'),
                   lambda route: held.append(route))
        page.get_by_role('button', name='User 2').click()
        page.wait_for_timeout(200)  # A's request is now waiting in `held`
        page.get_by_role('button', name='User 3').click()
        expect(page.locator('#message-rows')).to_contain_text('from B')

        held[0].continue_()
        page.wait_for_timeout(500)
        self.assertEqual(self.rows(page), ['from B'])
        self.assertFalse(Message.objects.get(text='from A').is_read, 'A was never on screen')


class HistoryTests(BrowserTestCase):
    def test_load_older_keeps_messages_in_order(self):
        # Codex #4. A page holds 50, so 53 messages make two pages.
        texts = [f'm{n:02}' for n in range(1, 54)]
        self.say(self.chat, self.friend, *texts)

        page = self.open_app()
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#message-rows .row')).to_have_count(50)
        page.get_by_role('button', name='Load older messages').click()
        expect(page.locator('#message-rows .row')).to_have_count(53)

        self.assertEqual(self.rows(page), texts)


class ChatListTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        # 51 chats: the friend's chat is the oldest and has no messages, so it's 51st.
        for n in range(3, 53):
            other = make_user(n)
            chat, _ = Chat.objects.get_or_create_chat(self.me, other)
            self.say(chat, other, 'hi')

    def test_clicking_show_more_twice_fetches_the_next_page_once(self):
        # Codex audit M-10: two clicks both fetched page 2 and both advanced, so page 3 was skipped.
        requested, held = [], []

        def hold_more(route):
            requested.append(route.request.url)
            held.append(route)

        page = self.open_app()
        page.route(re.compile(r'/api/v1/chats/\?page='), hold_more)
        more = page.get_by_role('button', name='Show more chats')
        more.click()
        more.click(force=True)   # force: a disabled button must ignore it, not Playwright
        self.wait_until(page, lambda: held)
        page.wait_for_timeout(300)
        for route in held:
            route.continue_()

        expect(page.locator('#chat-list li')).to_have_count(51)
        self.assertEqual(len(requested), 1)

    def test_chats_after_the_first_page_can_be_shown(self):
        # Codex #5.
        page = self.open_app()
        expect(page.locator('#chat-list li')).to_have_count(50)
        page.get_by_role('button', name='Show more chats').click()
        expect(page.locator('#chat-list li')).to_have_count(51)
        expect(page.get_by_role('button', name='Show more chats')).to_be_hidden()

    def test_the_poll_refreshes_chats_after_the_first_page(self):
        # Codex audit M-13: the poll fetched page 1 only, so page 2 kept its old unread count.
        message = Message.objects.create(chat=self.chat, sender=self.friend, text='old news')
        Message.objects.filter(pk=message.pk).update(created_at=message.created_at - timedelta(hours=1))
        page = self.open_app(setup=lambda p: p.clock.install())
        page.get_by_role('button', name='Show more chats').click()
        friend_row = page.locator('#chat-list li').filter(has=page.locator('.chat-name', has_text=re.compile('^User 2$')))
        expect(friend_row.locator('.badge')).to_have_text('1')

        Message.objects.filter(pk=message.pk).update(is_read=True)   # read in another tab
        page.clock.fast_forward(46_000)                              # the chat list poll

        expect(friend_row.locator('.badge')).to_have_count(0)

    def test_looking_up_someone_whose_chat_is_not_loaded_opens_it(self):
        page = self.open_app()
        page.get_by_placeholder('Find someone by phone…').fill(phone(2))
        page.keyboard.press('Enter')
        expect(page.locator('#peer-name')).to_have_text('User 2')


class PeerHeaderTests(BrowserTestCase):
    def test_the_poll_refreshes_the_open_chats_header(self):
        # Codex audit M-13: the header was drawn once, when the chat opened, and never again.
        page = self.open_app(setup=lambda p: p.clock.install())
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#peer-status')).to_have_text('offline')

        User.objects.filter(pk=self.friend.pk).update(first_name='Renamed', last_seen=timezone.now())
        page.clock.fast_forward(46_000)   # the chat list poll

        expect(page.locator('#peer-name')).to_have_text('Renamed')
        expect(page.locator('#peer-status')).to_contain_text('last seen')


class ComposerTests(BrowserTestCase):
    def send(self, page, text):
        page.get_by_role('button', name='User 2').click()
        page.locator('#composer-input').fill(text)
        page.keyboard.press('Enter')

    def test_a_rejected_message_keeps_its_text(self):
        # Codex #6.
        Block.objects.create(blocker=self.friend, blocked=self.me)
        page = self.open_app()
        self.send(page, 'please keep me')

        expect(page.locator('#send-error')).to_have_text("You can't send messages in this chat.")
        expect(page.locator('#composer-input')).to_have_value('please keep me')

    def test_a_delivered_message_clears_the_composer(self):
        page = self.open_app()
        self.send(page, 'hello')

        expect(page.locator('#message-rows')).to_contain_text('hello')
        expect(page.locator('#composer-input')).to_have_value('')


def is_message_frame(frame):
    try:
        return json.loads(frame).get('type') == 'message'
    except (TypeError, ValueError):
        return False


class SessionLifecycleTests(BrowserTestCase):
    """Codex audit H-04, H-06, M-12, L-03: what happens around logout, lost answers and failures."""

    def log_in(self, page, user):
        page.locator('#auth-form input[name=phone_number]').fill(str(user.phone_number))
        page.locator('#auth-form input[name=password]').fill(PASSWORD)
        page.locator('#auth-submit').click()
        expect(page.locator('#conn-state.is-open')).to_be_attached()

    def send(self, page, text):
        page.locator('#composer-input').fill(text)
        page.keyboard.press('Enter')

    def test_a_token_refresh_that_ends_after_logout_does_not_sign_back_in(self):
        page = self.open_app(refresh=True)
        held = []
        page.route('**/api/v1/auth/token/refresh/', lambda route: held.append(route))
        page.evaluate("state.access = 'expired'; void loadChats().catch(() => {})")  # its 401 starts a refresh
        self.wait_until(page, lambda: held)

        page.locator('#logout').click()
        held[0].continue_()
        page.wait_for_timeout(500)

        self.assertIsNone(page.evaluate("localStorage.getItem('access')"))
        expect(page.locator('#auth')).to_be_visible()

    def test_a_chat_list_from_before_logout_never_reaches_the_next_account(self):
        other = make_user(3)  # no chats of their own
        page = self.open_app()
        held = []
        page.route('**/api/v1/chats/', lambda route: route.continue_() if held else held.append(route))
        page.evaluate('void loadChats()')  # void: don't wait for the request we're holding
        self.wait_until(page, lambda: held)

        page.locator('#logout').click()
        self.log_in(page, other)
        held[0].continue_()
        page.wait_for_timeout(500)

        expect(page.locator('#chat-list')).not_to_contain_text('User 2')

    def test_a_send_waiting_at_logout_does_not_block_the_next_account(self):
        def drop_echoes(ws):
            server = ws.connect_to_server()
            ws.on_message(server.send)
            server.on_message(lambda frame: None if is_message_frame(frame) else ws.send(frame))

        page = self.open_app(setup=lambda p: p.route_web_socket('**/ws/inbox/**', drop_echoes))
        page.get_by_role('button', name='User 2').click()
        self.send(page, 'echo never comes')
        self.wait_until(page, lambda: Message.objects.filter(text='echo never comes').exists())

        page.locator('#logout').click()
        self.log_in(page, self.me)
        page.get_by_role('button', name='User 2').click()
        self.send(page, 'after logging back in')

        self.wait_until(page, lambda: Message.objects.filter(text='after logging back in').exists())

    def test_a_lost_echo_does_not_block_sending_and_the_saved_message_shows(self):
        def drop_echoes(ws):
            server = ws.connect_to_server()
            ws.on_message(server.send)
            server.on_message(lambda frame: None if is_message_frame(frame) else ws.send(frame))

        def setup(page):
            page.clock.install()
            page.route_web_socket('**/ws/inbox/**', drop_echoes)

        page = self.open_app(setup=setup)
        page.get_by_role('button', name='User 2').click()
        self.send(page, 'saved but no echo')
        self.wait_until(page, lambda: Message.objects.filter(text='saved but no echo').exists())

        page.clock.fast_forward(11_000)

        expect(page.locator('#message-rows')).to_contain_text('saved but no echo')
        expect(page.locator('#composer-input')).to_have_value('')
        self.send(page, 'the next one')
        self.wait_until(page, lambda: Message.objects.filter(text='the next one').exists())

    def test_a_message_that_never_arrived_keeps_its_text_and_says_so(self):
        def swallow_sends(ws):
            server = ws.connect_to_server()
            # Our message frames vanish on the way; pings still get through.
            ws.on_message(lambda frame: None if '"message"' in frame else server.send(frame))

        def setup(page):
            page.clock.install()
            page.route_web_socket('**/ws/inbox/**', swallow_sends)

        page = self.open_app(setup=setup)
        page.get_by_role('button', name='User 2').click()
        self.send(page, 'lost on the way')
        page.wait_for_timeout(300)
        page.clock.fast_forward(11_000)

        expect(page.locator('#send-error')).to_be_visible()
        expect(page.locator('#composer-input')).to_have_value('lost on the way')
        self.assertFalse(Message.objects.filter(text='lost on the way').exists())

    def test_a_connection_that_stops_answering_pings_is_replaced(self):
        connections = []

        def silent_after_hello(ws):
            server = ws.connect_to_server()
            connections.append(ws)
            answered = []
            ws.on_message(server.send)

            def from_server(frame):
                if not answered or len(connections) > 1:  # the first pong, and any later socket
                    answered.append(frame)
                    ws.send(frame)
            server.on_message(from_server)

        def setup(page):
            page.clock.install()
            page.route_web_socket('**/ws/inbox/**', silent_after_hello)

        page = self.open_app(setup=setup)
        page.clock.fast_forward(61_000)   # two ping periods with no answer
        page.clock.fast_forward(1_000)    # the reconnect's jitter
        self.wait_until(page, lambda: len(connections) > 1)
        expect(page.locator('#conn-state.is-open')).to_be_attached()

    def test_the_socket_connects_even_if_the_chat_list_fails_to_load(self):
        def fail_first(route):
            if not failed:
                failed.append(route)
                route.fulfill(status=500, body='')
            else:
                route.continue_()
        failed = []

        def setup(page):
            page.clock.install()
            page.route('**/api/v1/chats/', fail_first)

        page = self.open_app(setup=setup)        # waits for the socket
        page.clock.fast_forward(46_000)           # the next poll
        expect(page.locator('#chat-list')).to_contain_text('User 2')

    def test_a_network_error_at_startup_does_not_sign_out(self):
        def fail_first(route):
            if not failed:
                failed.append(route)
                route.abort()
            else:
                route.continue_()
        failed = []

        def setup(page):
            page.clock.install()
            page.route('**/api/v1/auth/profile/', fail_first)

        page = self.open_app(setup=setup, connected=False)
        self.wait_until(page, lambda: failed)
        page.clock.fast_forward(6_000)

        expect(page.locator('#conn-state.is-open')).to_be_attached()
        self.assertIsNotNone(page.evaluate("localStorage.getItem('access')"))

    def test_a_refresh_that_fails_on_the_network_retries_instead_of_stalling(self):
        connections, failed = [], []

        def forward(ws):
            server = ws.connect_to_server()
            connections.append(ws)
            ws.on_message(server.send)
            server.on_message(ws.send)

        def abort_first(route):
            if not failed:
                failed.append(route)
                route.abort()
            else:
                route.continue_()

        def setup(page):
            page.route_web_socket('**/ws/inbox/**', forward)
            page.route('**/api/v1/auth/token/refresh/', abort_first)

        page = self.open_app(refresh=True, setup=setup)
        connections[0].close(code=4401, reason='token expired')   # as the server does at expiry

        self.wait_until(page, lambda: len(connections) > 1, timeout=10)
        expect(page.locator('#conn-state.is-open')).to_be_attached()
        expect(page.locator('#app')).to_be_visible()

    def test_a_rate_limit_shows_the_servers_message(self):
        context = self.browser.new_context()   # signed out: the login screen
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(self.live_server_url)
        page.route('**/api/v1/auth/login/', lambda route: route.fulfill(
            status=429, content_type='application/json',
            body=json.dumps({'detail': 'Request was throttled. Expected available in 42 seconds.'})))
        page.locator('#auth-form input[name=phone_number]').fill(phone(1))
        page.locator('#auth-form input[name=password]').fill('wrong')
        page.locator('#auth-submit').click()

        expect(page.locator('#auth-error')).to_have_text('Request was throttled. Expected available in 42 seconds.')


class ReadReceiptTests(BrowserTestCase):
    """Codex audit M-06 and M-08: ticks follow what was really on screen, and survive missed events."""

    def ticks(self, page):
        return page.locator('#message-rows .row.out .meta').evaluate_all(
            'metas => metas.map(m => m.textContent.endsWith("✓✓") ? 2 : 1)')

    def test_read_names_the_newest_message_on_screen(self):
        self.say(self.chat, self.friend, 'one', 'two')
        newest = Message.objects.get(text='two')
        sent = []

        def record(ws):
            server = ws.connect_to_server()
            ws.on_message(lambda frame: (sent.append(frame), server.send(frame)))
            server.on_message(ws.send)

        page = self.open_app(setup=lambda p: p.route_web_socket('**/ws/inbox/**', record))
        page.get_by_role('button', name='User 2').click()

        self.wait_until(page, lambda: any('"read"' in f for f in sent))
        read = json.loads(next(f for f in sent if '"read"' in f))
        self.assertEqual(read, {'action': 'read', 'chat_id': self.chat.id, 'up_to': newest.id})

    def test_a_receipt_ticks_only_messages_up_to_its_boundary(self):
        self.say(self.chat, self.me, 'seen', 'not yet')
        seen = Message.objects.get(text='seen')
        sockets = []

        def keep(ws):
            server = ws.connect_to_server()
            sockets.append(ws)
            ws.on_message(server.send)
            server.on_message(ws.send)

        page = self.open_app(setup=lambda p: p.route_web_socket('**/ws/inbox/**', keep))
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#message-rows .row')).to_have_count(2)

        sockets[0].send(json.dumps({'type': 'read', 'chat_id': self.chat.id, 'by': self.friend.id,
                                    'up_to': seen.id, 'count': 1}))

        expect(page.locator('#message-rows .row.out .meta').first).to_contain_text('✓✓')
        self.assertEqual(self.ticks(page), [2, 1])

    def test_ticks_missed_while_the_receipt_was_lost_are_repaired(self):
        self.say(self.chat, self.me, 'mine')
        page = self.open_app(setup=lambda p: p.clock.install())
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#message-rows .row.out')).to_have_count(1)

        # Read while this page heard nothing: like a receipt sent while it was reconnecting.
        Message.objects.filter(text='mine').update(is_read=True)
        page.clock.fast_forward(46_000)   # the chat list poll

        expect(page.locator('#message-rows .row.out .meta')).to_contain_text('✓✓')


class OrderingTests(BrowserTestCase):
    """Codex audit M-03, M-09, M-10: messages show in order, gaps get filled, failed pages are retried."""

    def keep_sockets(self, sockets):
        def handler(ws):
            server = ws.connect_to_server()
            sockets.append(ws)
            ws.on_message(server.send)
            server.on_message(ws.send)
        return handler

    def live(self, ws, message):
        """Deliver `message` to the page as the server's socket would."""
        ws.send(json.dumps({'type': 'message', 'id': message.id, 'chat_id': message.chat_id,
                            'sender_id': message.sender_id, 'text': message.text,
                            'created_at': message.created_at.isoformat(), 'is_read': False, 'read_at': None}))

    def test_a_live_message_that_beats_the_history_still_lands_last(self):
        # M-09: it used to be drawn first, above the older history.
        self.say(self.chat, self.friend, 'older 1', 'older 2')
        sockets, held = [], []
        page = self.open_app(setup=lambda p: p.route_web_socket('**/ws/inbox/**', self.keep_sockets(sockets)))
        page.route(re.compile(rf'/api/v1/chats/{self.chat.id}/messages/(\?page=1)?$'), lambda route: held.append(route))
        page.get_by_role('button', name='User 2').click()
        self.wait_until(page, lambda: held)

        self.say(self.chat, self.friend, 'newest')
        self.live(sockets[0], Message.objects.get(text='newest'))
        expect(page.locator('#message-rows .row')).to_have_count(1)
        held[0].continue_()

        expect(page.locator('#message-rows .row')).to_have_count(3)
        self.assertEqual(self.rows(page), ['older 1', 'older 2', 'newest'])

    def test_a_message_missed_in_the_middle_is_fetched_after_a_reconnect(self):
        # M-03: the gap fetch started after the newest message seen, so a hole before it stayed a hole.
        self.say(self.chat, self.friend, 'one')
        sockets = []
        page = self.open_app(setup=lambda p: p.route_web_socket('**/ws/inbox/**', self.keep_sockets(sockets)))
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#message-rows .row')).to_have_count(1)

        self.say(self.chat, self.friend, 'two (its live event was lost)', 'three')
        self.live(sockets[0], Message.objects.get(text='three'))
        expect(page.locator('#message-rows .row')).to_have_count(2)

        sockets[0].close(code=1012, reason='server restart')   # the page reconnects and catches up
        self.wait_until(page, lambda: len(sockets) > 1, timeout=10)

        expect(page.locator('#message-rows .row')).to_have_count(3)
        self.assertEqual(self.rows(page), ['one', 'two (its live event was lost)', 'three'])

    def test_a_failed_older_page_is_retried_not_skipped(self):
        # M-10: the page counter moved on before the answer came, so a failure skipped a page.
        self.say(self.chat, self.friend, *[f'm{n:03}' for n in range(1, 121)])
        failed = []

        def fail_once(route):
            if failed:
                route.continue_()
            else:
                failed.append(route)
                route.fulfill(status=500, body='')

        page = self.open_app()
        page.get_by_role('button', name='User 2').click()
        expect(page.locator('#message-rows .row')).to_have_count(50)
        page.route(re.compile(r'/messages/\?(cursor=|page=[2-9])'), fail_once)
        older = page.get_by_role('button', name='Load older messages')

        older.click()
        self.wait_until(page, lambda: failed)
        page.wait_for_timeout(300)
        older.click()

        expect(page.locator('#message-rows .row')).to_have_count(100)
        self.assertEqual(self.rows(page)[0], 'm021')
