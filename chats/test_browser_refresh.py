"""PR #34: refresh loaded and lookup-opened chats even when numbered pages move."""
import re

from django.utils import timezone

from accounts.models import User
from chats.models import Block, Chat
from chats.test_browser import BrowserTestCase, expect
from test_helpers import make_user, phone


class ChatRefreshTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        for n in range(3, 53):
            other = make_user(n)
            chat, _ = Chat.objects.get_or_create_chat(self.me, other)
            self.say(chat, other, 'hi')

    def test_overlapping_pages_render_each_chat_once(self):
        page = self.open_app()
        chats = page.evaluate('api("/chats/").then(data => data.results.slice(0, 3))')
        page.route(re.compile(r'/api/v1/chats/\?page=2$'),
                   lambda route: route.fulfill(json={'results': chats[1:], 'next': None}))
        page.route(re.compile(r'/api/v1/chats/$'),
                   lambda route: route.fulfill(json={'results': chats[:2], 'next': '?page=2'}))
        page.evaluate('state.chatPages = 2; state.chats = []; void 0')
        page.evaluate('loadChats()')
        self.assertEqual(page.evaluate('state.chats.map(c => c.id)'), [c['id'] for c in chats])
        expect(page.locator('#chat-list li')).to_have_count(3)

    def test_lookup_opened_chat_refreshes_its_header_and_blocked_details(self):
        page = self.open_app()
        page.get_by_placeholder('Search by name or phone').fill(phone(2))
        page.keyboard.press('Enter')
        expect(page.locator('#peer-name')).to_have_text('User 2')
        self.assertEqual(page.evaluate('state.chatPages'), 1)
        User.objects.filter(pk=self.friend.pk).update(first_name='Renamed', last_seen=timezone.now(), avatar='avatars/peer.png')
        page.evaluate('loadChats()')
        expect(page.locator('#peer-name')).to_have_text('Renamed')
        expect(page.locator('#peer-status')).to_contain_text('last seen')
        expect(page.locator('#peer-avatar')).to_have_attribute('src', re.compile('avatars/peer.png$'))
        Block.objects.create(blocker=self.friend, blocked=self.me)
        page.evaluate('loadChats()')
        expect(page.locator('#peer-status')).to_have_text('offline')
        expect(page.locator('#peer-avatar')).to_have_attribute('src', re.compile('^data:'))
        self.assertIsNone(page.evaluate('state.peer.last_seen'))

    def test_a_vanished_last_page_does_not_stop_refreshes(self):
        page = self.open_app()
        page.get_by_role('button', name='Show more chats').click()
        expect(page.locator('#chat-list li')).to_have_count(51)
        page.locator('#chat-list li').filter(has=page.locator('.chat-name', has_text=re.compile('^User 2$'))).get_by_role('button').click()
        Chat.objects.exclude(pk=self.chat.pk).first().delete()
        User.objects.filter(pk=self.friend.pk).update(first_name='Renamed')
        requested = []
        snapshot = page.evaluate('api("/chats/")')
        snapshot['next'] = self.live_server_url + '/api/v1/chats/?page=2'

        def stale_next(route):
            route.fulfill(json=snapshot)

        def missing_page(route):
            requested.append(route.request.url)
            route.continue_()  # real server returns 404; the first page has already changed

        page.route(re.compile(r'/api/v1/chats/$'), stale_next)
        page.route(re.compile(r'/api/v1/chats/\?page=2$'), missing_page)
        status = page.evaluate('loadChats().then(() => null, err => err.status)')
        self.assertIsNone(status, 'a missing last page must not reject the whole refresh')
        self.assertTrue(requested)
        expect(page.locator('#peer-name')).to_have_text('Renamed')
        self.assertEqual(page.evaluate('state.chatPages'), 1)
        page.unroute(re.compile(r'/api/v1/chats/$'), stale_next)
        requested.clear()
        User.objects.filter(pk=self.friend.pk).update(first_name='Refreshed again')
        page.evaluate('loadChats()')
        expect(page.locator('#peer-name')).to_have_text('Refreshed again')
        self.assertEqual(requested, [])
