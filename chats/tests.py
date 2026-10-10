from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from chats.models import MAX_MESSAGE_LENGTH, Block, Chat, Message
from test_helpers import FakePresenceMixin, client_for, make_user

CHATS = '/api/v1/chats/'


def say(chat, sender, text, minutes_ago=0):
    message = Message.objects.create(chat=chat, sender=sender, text=text)
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return message


class StartChatTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me = make_user(1)
        self.other = make_user(2)

    def start(self, participant_id, user=None):
        return client_for(user or self.me).post(CHATS, {'participant_id': participant_id})

    def test_starting_a_chat_returns_it_with_the_other_participant(self):
        response = self.start(self.other.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['participant']['id'], self.other.id)
        self.assertEqual(response.data['unread_count'], 0)

    def test_the_same_pair_always_gets_the_same_chat(self):
        first = self.start(self.other.id).data['id']
        again = self.start(self.other.id).data['id']
        from_the_other_side = self.start(self.me.id, user=self.other).data['id']

        self.assertEqual(first, again)
        self.assertEqual(first, from_the_other_side)
        self.assertEqual(Chat.objects.count(), 1)

    def test_you_cannot_chat_with_yourself(self):
        self.assertEqual(self.start(self.me.id).status_code, 400)

    def test_a_user_who_blocked_you_looks_like_a_missing_user(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        blocked = self.start(self.other.id)
        missing = self.start(999999)

        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data, missing.data, 'a block must not be detectable')

    def test_requires_authentication(self):
        self.assertEqual(APIClient().post(CHATS, {'participant_id': self.other.id}).status_code, 401)

    def test_starting_chats_is_limited_to_30_an_hour_but_listing_is_not(self):
        # SEC-4: stops one account from messaging every user.
        cache.clear()
        self.addCleanup(cache.clear)
        for _ in range(30):
            self.assertEqual(self.start(self.other.id).status_code, 201)
        self.assertEqual(self.start(self.other.id).status_code, 429)
        self.assertEqual(client_for(self.me).get(CHATS).status_code, 200)
        self.assertEqual(self.start(self.me.id, user=self.other).status_code, 201,
                         'other users are unaffected')


class ChatListTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me, self.friend, self.colleague = make_user(1), make_user(2), make_user(3)
        self.with_friend, _ = Chat.objects.get_or_create_chat(self.me, self.friend)
        self.with_colleague, _ = Chat.objects.get_or_create_chat(self.me, self.colleague)

    def chats(self):
        return client_for(self.me).get(CHATS).data['results']

    def test_lists_only_my_chats(self):
        Chat.objects.get_or_create_chat(self.friend, self.colleague)
        self.assertEqual({c['id'] for c in self.chats()}, {self.with_friend.id, self.with_colleague.id})

    def test_shows_the_last_message_and_my_unread_count(self):
        say(self.with_friend, self.friend, 'hi', minutes_ago=3)
        say(self.with_friend, self.friend, 'are you there?', minutes_ago=2)
        say(self.with_friend, self.me, 'yes', minutes_ago=1)

        chat = next(c for c in self.chats() if c['id'] == self.with_friend.id)
        self.assertEqual(chat['last_message']['text'], 'yes')
        self.assertEqual(chat['unread_count'], 2, 'my own messages are never unread for me')

    def test_most_recent_conversation_comes_first(self):
        say(self.with_friend, self.friend, 'older', minutes_ago=10)
        say(self.with_colleague, self.colleague, 'newer', minutes_ago=1)
        self.assertEqual([c['id'] for c in self.chats()], [self.with_colleague.id, self.with_friend.id])

    def test_shows_whether_each_person_is_online(self):
        self.redis.sadd(f'presence:{self.friend.id}', 'some-channel')
        online = {c['participant']['id']: c['participant']['is_online'] for c in self.chats()}
        self.assertEqual(online, {self.friend.id: True, self.colleague.id: False})


@mock.patch('chats.views.broadcast_message')
class MessageTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me, self.friend, self.stranger = make_user(1), make_user(2), make_user(3)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.friend)
        self.url = f'{CHATS}{self.chat.id}/messages/'

    def send(self, text, user=None):
        return client_for(user or self.me).post(self.url, {'text': text})

    def test_history_is_newest_first(self, broadcast):
        say(self.chat, self.friend, 'first', minutes_ago=2)
        say(self.chat, self.me, 'second', minutes_ago=1)

        texts = [m['text'] for m in client_for(self.me).get(self.url).data['results']]
        self.assertEqual(texts, ['second', 'first'])

    def test_sending_saves_the_message_and_pushes_it_to_open_sockets(self, broadcast):
        response = self.send('hello')

        self.assertEqual(response.status_code, 201)
        message = Message.objects.get()
        self.assertEqual((message.sender, message.text), (self.me, 'hello'))
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args[0], message)

    def test_outsiders_cannot_read_or_post(self, broadcast):
        self.assertEqual(client_for(self.stranger).get(self.url).status_code, 404)
        self.assertEqual(self.send('let me in', user=self.stranger).status_code, 404)
        self.assertFalse(Message.objects.exists())

    def test_a_block_either_way_stops_new_messages(self, broadcast):
        for blocker, blocked in ((self.friend, self.me), (self.me, self.friend)):
            with self.subTest(blocker=blocker.first_name):
                block = Block.objects.create(blocker=blocker, blocked=blocked)
                self.assertEqual(self.send('hello').status_code, 403)
                block.delete()
        self.assertFalse(Message.objects.exists())
        broadcast.assert_not_called()

    def test_message_length_is_limited(self, broadcast):
        self.assertEqual(self.send('x' * MAX_MESSAGE_LENGTH).status_code, 201)
        self.assertEqual(self.send('x' * (MAX_MESSAGE_LENGTH + 1)).status_code, 400)
        self.assertEqual(Message.objects.count(), 1)

    def test_blank_messages_are_rejected(self, broadcast):
        self.assertEqual(self.send('   ').status_code, 400)

    def test_after_returns_only_newer_messages_oldest_first(self, broadcast):
        # COR-1: how a reconnecting client fetches what the socket missed.
        seen = say(self.chat, self.friend, 'seen', minutes_ago=3)
        say(self.chat, self.friend, 'missed 1', minutes_ago=2)
        say(self.chat, self.me, 'missed 2', minutes_ago=1)

        data = client_for(self.me).get(self.url, {'after': seen.id}).data
        self.assertEqual([m['text'] for m in data['results']], ['missed 1', 'missed 2'])
        self.assertIsNone(data['next'])

    def test_after_must_be_a_whole_number(self, broadcast):
        for bad in ('abc', '-1', '1.5', ''):
            with self.subTest(after=bad):
                self.assertEqual(client_for(self.me).get(self.url, {'after': bad}).status_code, 400)


class MarkReadTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me, self.friend = make_user(1), make_user(2)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.friend)
        self.url = f'{CHATS}{self.chat.id}/read/'

    def test_marks_only_the_other_persons_messages(self):
        theirs = [say(self.chat, self.friend, 'one'), say(self.chat, self.friend, 'two')]
        mine = say(self.chat, self.me, 'three')

        response = client_for(self.me).post(self.url)

        self.assertEqual(response.data, {'marked_read': 2})
        for message in theirs:
            message.refresh_from_db()
            self.assertTrue(message.is_read)
            self.assertIsNotNone(message.read_at)
        mine.refresh_from_db()
        self.assertFalse(mine.is_read)
        self.assertEqual(client_for(self.me).post(self.url).data, {'marked_read': 0})

    def test_outsiders_get_404(self):
        self.assertEqual(client_for(make_user(3)).post(self.url).status_code, 404)
