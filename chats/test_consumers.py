"""The inbox WebSocket, driven through the full ASGI stack: origin check, JWT
middleware, URL router and consumer, as a browser would reach it."""
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import TestCase

from chats.consumers import CLOSE_UNAUTHENTICATED
from chats.models import MAX_MESSAGE_LENGTH, Block, Chat, Message
from root.asgi import application
from test_helpers import FakePresenceMixin, client_for, make_user, token_for

ALLOWED_ORIGIN = [(b'origin', b'http://localhost')]


class InboxSocketTestCase(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.alice, self.bob, self.carol = make_user(1), make_user(2), make_user(3)
        self.chat, _ = Chat.objects.get_or_create_chat(self.alice, self.bob)
        self.sockets = []

    async def open(self, user=None, token=None, origin=ALLOWED_ORIGIN):
        token = token_for(user) if user is not None else token
        socket = WebsocketCommunicator(application, f'/ws/inbox/?token={token}', headers=origin)
        connected, close_code = await socket.connect()
        if connected:
            self.sockets.append(socket)
            return socket
        return close_code

    async def close_all(self):
        for socket in self.sockets:
            await socket.disconnect()
        self.sockets.clear()

    def online(self, user):
        return self.redis.scard(f'presence:{user.id}') > 0


class ConnectionTests(InboxSocketTestCase):
    async def test_a_valid_token_connects_and_marks_the_user_online(self):
        await self.open(self.alice)
        self.assertTrue(self.online(self.alice))

        await self.close_all()
        self.assertFalse(self.online(self.alice))

    async def test_missing_or_invalid_tokens_are_refused(self):
        for token in ('', 'not-a-jwt'):
            with self.subTest(token=token):
                self.assertEqual(await self.open(token=token), CLOSE_UNAUTHENTICATED)

    async def test_other_websites_cannot_open_the_socket(self):
        # Stops a malicious page from using a visitor's token from its own origin.
        result = await self.open(self.alice, origin=[(b'origin', b'https://evil.example')])
        self.assertNotIsInstance(result, WebsocketCommunicator)

    async def test_ping_answers_pong(self):
        socket = await self.open(self.alice)
        await socket.send_json_to({'action': 'ping'})
        self.assertEqual(await socket.receive_json_from(), {'type': 'pong'})
        await self.close_all()

    async def test_presence_lasts_until_the_last_tab_closes(self):
        first_tab = await self.open(self.alice)
        await self.open(self.alice)

        await first_tab.disconnect()
        self.sockets.remove(first_tab)
        self.assertTrue(self.online(self.alice))
        await self.close_all()
        self.assertFalse(self.online(self.alice))


class MessagingTests(InboxSocketTestCase):
    async def test_a_message_reaches_both_participants_and_nobody_else(self):
        alice, bob, carol = [await self.open(u) for u in (self.alice, self.bob, self.carol)]

        await alice.send_json_to({'chat_id': self.chat.id, 'text': '  salom  '})

        for socket in (alice, bob):
            event = await socket.receive_json_from()
            self.assertEqual((event['type'], event['text'], event['sender_id']),
                             ('message', 'salom', self.alice.id))
        self.assertTrue(await carol.receive_nothing())
        saved = await database_sync_to_async(Message.objects.get)()
        self.assertEqual((saved.sender_id, saved.text), (self.alice.id, 'salom'))
        await self.close_all()

    async def test_every_open_tab_receives_it(self):
        tabs = [await self.open(self.alice), await self.open(self.alice)]
        bob = await self.open(self.bob)

        await bob.send_json_to({'chat_id': self.chat.id, 'text': 'hi'})

        for tab in tabs:
            self.assertEqual((await tab.receive_json_from())['text'], 'hi')
        await self.close_all()

    async def test_you_cannot_post_into_someone_elses_chat(self):
        carol = await self.open(self.carol)
        alice = await self.open(self.alice)

        await carol.send_json_to({'chat_id': self.chat.id, 'text': 'let me in'})

        self.assertEqual(await carol.receive_json_from(),
                         {'type': 'error', 'detail': 'No such chat.', 'chat_id': None})
        self.assertTrue(await alice.receive_nothing())
        self.assertFalse(await database_sync_to_async(Message.objects.exists)())
        await self.close_all()

    async def test_text_is_validated(self):
        alice = await self.open(self.alice)

        for text in ('', '   ', 'x' * (MAX_MESSAGE_LENGTH + 1)):
            with self.subTest(length=len(text)):
                await alice.send_json_to({'chat_id': self.chat.id, 'text': text})
                self.assertEqual((await alice.receive_json_from())['type'], 'error')

        await alice.send_json_to({'chat_id': self.chat.id, 'text': 'x' * MAX_MESSAGE_LENGTH})
        self.assertEqual((await alice.receive_json_from())['type'], 'message')
        self.assertEqual(await database_sync_to_async(Message.objects.count)(), 1)
        await self.close_all()

    async def test_a_block_either_way_stops_new_messages(self):
        alice = await self.open(self.alice)
        bob = await self.open(self.bob)
        await database_sync_to_async(Block.objects.create)(blocker=self.bob, blocked=self.alice)

        await alice.send_json_to({'chat_id': self.chat.id, 'text': 'hello?'})

        self.assertEqual((await alice.receive_json_from())['type'], 'error')
        self.assertTrue(await bob.receive_nothing())
        self.assertFalse(await database_sync_to_async(Message.objects.exists)())
        await self.close_all()

    async def test_malformed_input_gets_an_error_not_a_crash(self):
        alice = await self.open(self.alice)

        await alice.send_to(text_data='{not json')
        self.assertEqual((await alice.receive_json_from())['detail'], 'Malformed JSON.')
        await alice.send_json_to({'action': 'dance', 'chat_id': self.chat.id})
        self.assertEqual((await alice.receive_json_from())['type'], 'error')
        await alice.send_json_to({'chat_id': str(self.chat.id), 'text': 'id as a string'})
        self.assertEqual((await alice.receive_json_from())['detail'], 'No such chat.')

        await alice.send_json_to({'action': 'ping'})
        self.assertEqual(await alice.receive_json_from(), {'type': 'pong'}, 'socket still works')
        await self.close_all()

    async def test_a_message_sent_over_rest_reaches_open_sockets(self):
        bob = await self.open(self.bob)

        response = await database_sync_to_async(client_for(self.alice).post)(
            f'/api/v1/chats/{self.chat.id}/messages/', {'text': 'via REST'},
        )

        self.assertEqual(response.status_code, 201)
        event = await bob.receive_json_from()
        self.assertEqual((event['type'], event['text']), ('message', 'via REST'))
        await self.close_all()


class ReadReceiptTests(InboxSocketTestCase):
    async def test_reading_a_chat_marks_it_and_tells_both_sides(self):
        create = database_sync_to_async(Message.objects.create)
        await create(chat=self.chat, sender=self.bob, text='one')
        await create(chat=self.chat, sender=self.bob, text='two')
        await create(chat=self.chat, sender=self.alice, text='mine')
        alice, bob = await self.open(self.alice), await self.open(self.bob)

        await alice.send_json_to({'action': 'read', 'chat_id': self.chat.id})

        expected = {'type': 'read', 'chat_id': self.chat.id, 'by': self.alice.id, 'count': 2}
        self.assertEqual(await alice.receive_json_from(), expected)
        self.assertEqual(await bob.receive_json_from(), expected)
        unread = await database_sync_to_async(
            lambda: list(Message.objects.filter(is_read=False).values_list('text', flat=True))
        )()
        self.assertEqual(unread, ['mine'])
        await self.close_all()
