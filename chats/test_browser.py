"""The real app.js in a real browser (Chromium, through Playwright) against a live server.

The server runs in a separate process (Daphne), so it needs a database and channel layer that
two processes can share: Postgres and Redis. Runs in the CI job test-postgres-redis; skipped on
the SQLite settings. Locally: docker compose up -d, playwright install chromium, then
python manage.py test chats.test_browser.
"""
import os
import unittest

from channels.testing import ChannelsLiveServerTestCase
from django.db import connection

from chats.models import Block, Chat, Message
from test_helpers import make_user, phone, token_for

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
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as error:  # browser not downloaded
            cls.playwright.stop()
            super().tearDownClass()
            raise unittest.SkipTest(f'needs Chromium: {error}') from error

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)

    def setUp(self):
        super().setUp()
        self.me, self.friend = make_user(1), make_user(2)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.friend)

    def open_app(self, user=None):
        """Load the app signed in as `user`, the way a returning visitor arrives."""
        context = self.browser.new_context()
        self.addCleanup(context.close)
        context.add_init_script(f"localStorage.setItem('access', '{token_for(user or self.me)}')")
        page = context.new_page()
        page.goto(self.live_server_url)
        expect(page.locator('#conn-state.is-open')).to_be_attached()
        return page

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
        page.route(f'**/api/v1/chats/{self.chat.id}/messages/?page=1', lambda route: held.append(route))
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

    def test_chats_after_the_first_page_can_be_shown(self):
        # Codex #5.
        page = self.open_app()
        expect(page.locator('#chat-list li')).to_have_count(50)
        page.get_by_role('button', name='Show more chats').click()
        expect(page.locator('#chat-list li')).to_have_count(51)
        expect(page.get_by_role('button', name='Show more chats')).to_be_hidden()

    def test_looking_up_someone_whose_chat_is_not_loaded_opens_it(self):
        page = self.open_app()
        page.get_by_placeholder('Find someone by phone…').fill(phone(2))
        page.keyboard.press('Enter')
        expect(page.locator('#peer-name')).to_have_text('User 2')


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
