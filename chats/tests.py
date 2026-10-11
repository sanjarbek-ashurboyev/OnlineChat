from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from chats import presence
from chats.models import MAX_MESSAGE_LENGTH, Block, Chat, Message
from test_helpers import FakePresenceMixin, client_for, make_user, token_for

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

    def test_shows_how_far_the_other_person_has_read_my_messages(self):
        # Codex audit M-08: a client that missed read receipts while offline repairs them from this.
        first = say(self.with_friend, self.me, 'one', minutes_ago=3)
        say(self.with_friend, self.me, 'two', minutes_ago=2)
        say(self.with_friend, self.friend, 'theirs, read by me', minutes_ago=1)
        Message.objects.filter(chat=self.with_friend).exclude(text='two').update(is_read=True)

        by_id = {c['id']: c for c in self.chats()}
        self.assertEqual(by_id[self.with_friend.id]['peer_read_up_to'], first.id)
        self.assertIsNone(by_id[self.with_colleague.id]['peer_read_up_to'])

    def test_shows_whether_each_person_is_online(self):
        presence.mark_online(self.friend.id, 'some-channel')
        online = {c['participant']['id']: c['participant']['is_online'] for c in self.chats()}
        self.assertEqual(online, {self.friend.id: True, self.colleague.id: False})

    def show_everything(self, user):
        User.objects.filter(pk=user.pk).update(avatar='avatars/face.png', last_seen=timezone.now())
        presence.mark_online(user.id, 'some-channel')

    def participant(self, chat):
        return next(c for c in self.chats() if c['id'] == chat.id)['participant']

    def test_someone_who_blocked_you_shows_no_photo_or_status(self):
        # Codex audit M-14: GET /users/<id>/ hides them; the chat list used to show it all anyway.
        self.show_everything(self.friend)
        Block.objects.create(blocker=self.friend, blocked=self.me)

        self.assertEqual(self.participant(self.with_friend), {
            'id': self.friend.id, 'display_name': 'User 2',
            'avatar': None, 'is_online': False, 'last_seen': None,
        })

    def test_someone_you_blocked_still_shows_their_photo_and_status(self):
        # Only their block hides them from you, as on the profile endpoint.
        self.show_everything(self.friend)
        Block.objects.create(blocker=self.me, blocked=self.friend)

        participant = self.participant(self.with_friend)
        self.assertTrue(participant['is_online'])
        self.assertIsNotNone(participant['avatar'])
        self.assertIsNotNone(participant['last_seen'])


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

    def test_a_failed_broadcast_still_answers_201_for_a_saved_message(self, broadcast):
        # Codex audit M-04: the sender used to get a 500 for a message that was saved, and retried.
        broadcast.side_effect = ConnectionError('Redis is down')

        with self.assertLogs('chats.views', 'ERROR'):
            response = self.send('saved anyway')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Message.objects.get().text, 'saved anyway')

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

    def test_sending_is_limited_to_60_a_minute_but_reading_is_not(self, broadcast):
        # Matches the socket's sustained 1 message/s, so REST is not a way around it.
        cache.clear()
        self.addCleanup(cache.clear)
        for _ in range(60):
            self.assertEqual(self.send('hi').status_code, 201)
        self.assertEqual(self.send('one too many').status_code, 429)
        self.assertEqual(client_for(self.me).get(self.url).status_code, 200)
        self.assertEqual(self.send('hi', user=self.friend).status_code, 201,
                         'the other participant is unaffected')

    def test_a_disabled_account_cannot_use_its_token(self, broadcast):
        token = token_for(self.me)
        self.me.is_active = False
        self.me.save()

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(client.post(self.url, {'text': 'hi'}).status_code, 401)

    def test_blank_messages_are_rejected(self, broadcast):
        self.assertEqual(self.send('   ').status_code, 400)

    def test_older_history_stays_put_when_new_messages_arrive(self, broadcast):
        # Codex audit M-11: page 2 was "skip 50 from the newest", so 50 new messages made it repeat page 1.
        for n in range(60):
            say(self.chat, self.friend, f'old {n}')
        first = client_for(self.me).get(self.url).data
        for n in range(50):
            say(self.chat, self.friend, f'new {n}')

        older = client_for(self.me).get(first['next']).data

        self.assertEqual([m['text'] for m in older['results']], [f'old {n}' for n in range(9, -1, -1)])

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


@mock.patch('chats.views.broadcast_read')
class MarkReadTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me, self.friend = make_user(1), make_user(2)
        self.chat, _ = Chat.objects.get_or_create_chat(self.me, self.friend)
        self.url = f'{CHATS}{self.chat.id}/read/'

    def read(self, up_to, user=None):
        return client_for(user or self.me).post(self.url, {'up_to': up_to}, format='json')

    def test_marks_only_the_other_persons_messages(self, broadcast):
        theirs = [say(self.chat, self.friend, 'one'), say(self.chat, self.friend, 'two')]
        mine = say(self.chat, self.me, 'three')

        response = self.read(mine.id)

        self.assertEqual(response.data, {'marked_read': 2})
        for message in theirs:
            message.refresh_from_db()
            self.assertTrue(message.is_read)
            self.assertIsNotNone(message.read_at)
        mine.refresh_from_db()
        self.assertFalse(mine.is_read)
        self.assertEqual(self.read(mine.id).data, {'marked_read': 0})

    def test_only_messages_up_to_the_one_displayed_are_marked(self, broadcast):
        # Codex audit M-06: a message that arrived after the screen was drawn was marked read too.
        shown = say(self.chat, self.friend, 'on screen')
        not_shown = say(self.chat, self.friend, 'arrived meanwhile')

        self.assertEqual(self.read(shown.id).data, {'marked_read': 1})

        not_shown.refresh_from_db()
        self.assertFalse(not_shown.is_read)

    def test_the_sender_is_told(self, broadcast):
        # Codex audit M-07: only the socket path used to notify the sender.
        message = say(self.chat, self.friend, 'hi')
        self.read(message.id)
        broadcast.assert_called_once_with(self.chat, self.me, message.id, 1)

    def test_up_to_is_required_and_must_be_a_message_id(self, broadcast):
        for body in ({}, {'up_to': 'x'}, {'up_to': -1}, {'up_to': True}):
            with self.subTest(body=body):
                response = client_for(self.me).post(self.url, body, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('up_to', response.data)
        broadcast.assert_not_called()

    def test_outsiders_get_404(self, broadcast):
        self.assertEqual(self.read(1, user=make_user(3)).status_code, 404)
