import json
import logging

from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from chats import presence
from chats.models import MAX_MESSAGE_LENGTH, Block, Chat, Message

logger = logging.getLogger(__name__)

CLOSE_UNAUTHENTICATED = 4401


def group_for_user(user_id):
    """One group per person, not per chat.

    A per-chat group only reaches whoever has that conversation open, so
    messages in any other chat go unseen until the next poll.
    """
    return f'user_{user_id}'


def serialize(message):
    return {
        'id': message.id,
        'chat_id': message.chat_id,
        'sender_id': message.sender_id,
        'text': message.text,
        'created_at': message.created_at.isoformat(),
        'is_read': message.is_read,
        'read_at': message.read_at.isoformat() if message.read_at else None,
    }


def broadcast_message(message, chat=None):
    """Deliver a message to both participants. Safe to call from sync code.

    The REST send endpoint calls this too, so an HTTP-posted message still
    reaches connected sockets. Pass `chat` when the caller already has it
    loaded to avoid a lookup.
    """
    chat = chat or message.chat
    payload = {'type': 'chat.message', 'message': serialize(message)}
    layer = get_channel_layer()
    for user_id in (chat.user1_id, chat.user2_id):
        async_to_sync(layer.group_send)(group_for_user(user_id), payload)


class InboxConsumer(AsyncWebsocketConsumer):
    """One socket per signed-in user, carrying every chat they belong to."""

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        self.group = group_for_user(self.user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        # Presence follows the app being open, not a chat being selected.
        await sync_to_async(presence.mark_online)(self.user.pk, self.channel_name)
        await self.touch_last_seen()

    async def disconnect(self, code):
        if hasattr(self, 'group'):
            try:
                await self.channel_layer.group_discard(self.group, self.channel_name)
            except Exception:
                # Don't let a channel layer failure (e.g. MaxConnectionsError under a
                # burst of disconnects) skip marking the user offline below. The stale
                # group entry expires on its own (channels_redis group_expiry).
                logger.exception('inbox: group_discard failed for user %s', self.user.pk)
        if getattr(self, 'user', None) and self.user.is_authenticated:
            await sync_to_async(presence.mark_offline)(self.user.pk, self.channel_name)
            await self.touch_last_seen()

    async def receive(self, text_data=None, bytes_data=None):
        try:
            payload = json.loads(text_data or '')
        except json.JSONDecodeError:
            await self.send_error('Malformed JSON.')
            return

        await self.touch_last_seen()
        action = payload.get('action', 'message')

        if action == 'ping':
            await sync_to_async(presence.refresh)(self.user.pk)
            await self.send(text_data=json.dumps({'type': 'pong'}))
            return

        if action not in ('message', 'read'):
            await self.send_error(f'Unknown action {action!r}.')
            return

        chat = await self.get_chat(payload.get('chat_id'))
        if chat is None:
            await self.send_error('No such chat.')
            return

        if action == 'read':
            marked = await self.mark_read(chat.pk)
            await self.notify_read(chat, marked)
            return

        text = (payload.get('text') or '').strip()
        if not text:
            await self.send_error('text must not be empty.', chat_id=chat.pk)
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            await self.send_error(f'text must be at most {MAX_MESSAGE_LENGTH} characters.',
                                  chat_id=chat.pk)
            return

        if await self.is_blocked(chat):
            await self.send_error("You can't send messages in this chat.",
                                  chat_id=chat.pk)
            return

        message = await self.save_message(chat, text)
        for user_id in (chat.user1_id, chat.user2_id):
            await self.channel_layer.group_send(
                group_for_user(user_id),
                {'type': 'chat.message', 'message': serialize(message)},
            )

    async def notify_read(self, chat, count):
        for user_id in (chat.user1_id, chat.user2_id):
            await self.channel_layer.group_send(
                group_for_user(user_id),
                {'type': 'chat.read', 'chat_id': chat.pk,
                 'by': self.user.pk, 'count': count},
            )

    # -- group event handlers -------------------------------------------------

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'message', **event['message']}))

    async def chat_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read', 'chat_id': event['chat_id'],
            'by': event['by'], 'count': event['count'],
        }))

    # -- helpers --------------------------------------------------------------

    async def send_error(self, detail, chat_id=None):
        await self.send(text_data=json.dumps(
            {'type': 'error', 'detail': detail, 'chat_id': chat_id}))

    @database_sync_to_async
    def get_chat(self, chat_id):
        if not isinstance(chat_id, int):
            return None
        return (
            Chat.objects
            .filter(Q(user1=self.user) | Q(user2=self.user), pk=chat_id)
            .first()
        )

    @database_sync_to_async
    def is_blocked(self, chat):
        other_id = chat.user2_id if chat.user1_id == self.user.pk else chat.user1_id
        return Block.objects.filter(
            Q(blocker_id=other_id, blocked=self.user)
            | Q(blocker=self.user, blocked_id=other_id)
        ).exists()

    @database_sync_to_async
    def save_message(self, chat, text):
        return Message.objects.create(chat=chat, sender=self.user, text=text)

    @database_sync_to_async
    def mark_read(self, chat_id):
        return (
            Message.objects
            .filter(chat_id=chat_id, is_read=False)
            .exclude(sender=self.user)
            .update(is_read=True, read_at=timezone.now())
        )

    @database_sync_to_async
    def touch_last_seen(self):
        User.objects.filter(pk=self.user.pk).update(last_seen=timezone.now())
