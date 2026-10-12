"""The refresh filter uses the same annotations, membership and privacy as the chat list."""
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from chats import presence
from chats.models import Block, Chat
from test_helpers import FakePresenceMixin, client_for, make_user


class ChatRefreshFilterTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me, self.peer, self.other = make_user(1), make_user(2), make_user(3)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.peer)
        Chat.objects.get_or_create_chat(self.me, self.other)
        self.client = client_for(self.me)

    def test_refresh_returns_only_the_selected_chat_with_blocked_details_hidden(self):
        User.objects.filter(pk=self.peer.pk).update(avatar='avatars/peer.png', last_seen=timezone.now())
        presence.mark_online(self.peer.pk, 'test-peer')
        Block.objects.create(blocker=self.peer, blocked=self.me)
        response = self.client.get('/api/v1/chats/', {'chat_id': self.chat.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c['id'] for c in response.data['results']], [self.chat.pk])
        peer = response.data['results'][0]['participant']
        self.assertIsNone(peer['avatar'])
        self.assertIsNone(peer['last_seen'])
        self.assertFalse(peer['is_online'])
        self.assertIn('peer_read_up_to', response.data['results'][0])

    def test_refresh_never_returns_an_outsiders_chat(self):
        outsider_chat, _ = Chat.objects.get_or_create_chat(self.peer, self.other)
        response = self.client.get('/api/v1/chats/', {'chat_id': outsider_chat.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_creation_ignores_the_get_only_refresh_filter(self):
        response = self.client.post(f'/api/v1/chats/?chat_id={self.chat.pk}',
                                    {'participant_id': self.other.pk}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['participant']['id'], self.other.pk)

    def test_refresh_rejects_invalid_chat_ids(self):
        for value in ('bad', '-1', '0', '1.5'):
            with self.subTest(value):
                response = self.client.get('/api/v1/chats/', {'chat_id': value})
                self.assertEqual(response.status_code, 400)
                self.assertIn('chat_id', response.data)
