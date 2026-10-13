import asyncio
import json
import logging
import time

from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from chats import presence
from chats.models import Block, Chat, Message
from chats.ratelimit import TokenBucket
from chats.serializers import MessageSerializer

logger = logging.getLogger(__name__)

CLOSE_UNAUTHENTICATED = 4401
CLOSE_TOO_MANY_SOCKETS = 4429

# SEC-5. Per socket: 10 frames at once, then 1 per second. Per user: 5 sockets (tabs).
FRAMES_PER_SECOND, FRAME_BURST = 1, 10
MAX_SOCKETS_PER_USER = 5

# Codex audit H-01: a socket keeps its rights only while its token is valid and its account active.
# The token's expiry is exact; the account is re-checked this often.
AUTH_RECHECK_SECONDS = 60
# Codex audit M-02: the channel layer drops a group member after group_expiry (24 h), and the socket
# then gets nothing. Closing it well before means the browser reconnects and joins again.
MAX_SOCKET_SECONDS = 12 * 60 * 60
# T-15 (PERF-3): frames write last_seen at most this often per socket, like REST's TOUCH_INTERVAL. Connect and
# disconnect always write it; in between, "online" comes from presence, not from last_seen.
LAST_SEEN_INTERVAL = 60


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


def is_message_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def mark_read(chat, reader, up_to):
    """Mark the other person's messages read, up to id `up_to`: the newest one `reader` has on screen.

    A message that arrived after that isn't read yet (Codex audit M-06). The socket and REST both
    use this, and both tell the sender (M-07).
    """
    return (
        chat.messages
        .filter(is_read=False, id__lte=up_to)
        .exclude(sender=reader)
        .update(is_read=True, read_at=timezone.now())
    )


def read_event(chat, reader_id, up_to, count):
    return {'type': 'chat.read', 'chat_id': chat.pk, 'by': reader_id, 'up_to': up_to, 'count': count}


def broadcast_read(chat, reader, up_to, count):
    """Tell both participants about a read. Safe to call from sync code (the REST view)."""
    layer = get_channel_layer()
    for user_id in (chat.user1_id, chat.user2_id):
        async_to_sync(layer.group_send)(group_for_user(user_id), read_event(chat, reader.pk, up_to, count))


class InboxConsumer(AsyncWebsocketConsumer):
    """One socket per signed-in user, carrying every chat they belong to."""

    async def connect(self):
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.refuse(CLOSE_UNAUTHENTICATED)
            return
        # Counts and registers this socket in one step, which also marks the user online:
        # presence follows the app being open, not a chat being selected.
        if not await sync_to_async(presence.admit)(self.user.pk, self.channel_name, MAX_SOCKETS_PER_USER):
            await self.refuse(CLOSE_TOO_MANY_SOCKETS)
            return
        try:
            self.bucket = TokenBucket(rate=FRAMES_PER_SECOND, burst=FRAME_BURST)
            self.group = group_for_user(self.user.pk)
            await self.channel_layer.group_add(self.group, self.channel_name)
            await self.accept()
        except Exception:
            # disconnect() won't run for a consumer that failed here; give the slot back.
            await sync_to_async(presence.mark_offline)(self.user.pk, self.channel_name)
            raise
        await self.touch_last_seen()
        self.deadline = min(self.scope['token_exp'], time.time() + MAX_SOCKET_SECONDS)
        self.watchdog = asyncio.create_task(self.watch_rights())

    async def disconnect(self, code):
        if hasattr(self, 'watchdog'):
            self.watchdog.cancel()
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

    async def watch_rights(self):
        """Close at the deadline (token expiry or MAX_SOCKET_SECONDS), or once the account is disabled.

        4401 makes the browser renew its token and reconnect (assets/app.js).
        """
        while True:
            await asyncio.sleep(max(0, min(self.deadline - time.time(), AUTH_RECHECK_SECONDS)))
            if time.time() >= self.deadline:
                break
            try:
                if not await self.still_active():
                    break
            except Exception:
                # Try again next time. The deadline still holds, because the loop goes on.
                logger.exception('inbox: account check failed for user %s', self.user.pk)
        await self.close(code=CLOSE_UNAUTHENTICATED)

    async def refuse(self, code):
        # Accept, then close. A close before accept is an HTTP 403, and the browser
        # only sees code 1006, never ours (COR-5).
        self.refused = True
        await self.accept()
        await self.close(code=code)

    async def receive(self, text_data=None, bytes_data=None):
        if getattr(self, 'refused', False):
            return  # a frame that got in before our close
        # Every frame counts against the rate limit, pings included.
        if not self.bucket.take():
            await self.send_error('Slow down.')
            return

        try:
            payload = json.loads(text_data or '')
        except ValueError:  # JSONDecodeError, and ints too long to convert (Codex audit M-05)
            await self.send_error('Malformed JSON.')
            return
        if not isinstance(payload, dict):
            await self.send_error('Expected a JSON object.')
            return

        if time.monotonic() - self.last_seen_at >= LAST_SEEN_INTERVAL:
            await self.touch_last_seen()
        action = payload.get('action', 'message')

        if action == 'ping':
            await sync_to_async(presence.refresh)(self.user.pk, self.channel_name)
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
            up_to = payload.get('up_to')
            if not is_message_id(up_to):
                await self.send_error('up_to must be a message id.', chat_id=chat.pk)
                return
            marked = await database_sync_to_async(mark_read)(chat, self.user, up_to)
            await self.notify_read(chat, up_to, marked)
            return

        text = payload.get('text') or ''
        if not isinstance(text, str):
            await self.send_error('text must be a string.', chat_id=chat.pk)
            return
        # REST's own checks (blank, length, NUL, surrogates), so both doors accept the same text (M-05).
        serializer = MessageSerializer(data={'text': text})
        if not serializer.is_valid():
            await self.send_error(serializer.errors['text'][0], chat_id=chat.pk)
            return
        text = serializer.validated_data['text']  # trimmed

        if await self.is_blocked(chat):
            await self.send_error("You can't send messages in this chat.",
                                  chat_id=chat.pk)
            return

        message = await self.save_message(chat, text)
        event = {'type': 'chat.message', 'message': serialize(message)}
        try:
            for user_id in (chat.user1_id, chat.user2_id):
                await self.channel_layer.group_send(group_for_user(user_id), event)
        except Exception:
            # It's saved, and the sender must know, or they'll send it again: answer this socket
            # directly. Everyone else finds it through the gap fetch or the chat list (Codex audit M-04).
            logger.exception('inbox: broadcast failed for message %s', message.pk)
            await self.chat_message(event)

    async def notify_read(self, chat, up_to, count):
        for user_id in (chat.user1_id, chat.user2_id):
            await self.channel_layer.group_send(
                group_for_user(user_id), read_event(chat, self.user.pk, up_to, count))

    # -- group event handlers -------------------------------------------------

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({'type': 'message', **event['message']}))

    async def chat_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read', 'chat_id': event['chat_id'],
            'by': event['by'], 'up_to': event['up_to'], 'count': event['count'],
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
    def still_active(self):
        return User.objects.filter(pk=self.user.pk, is_active=True).exists()

    @database_sync_to_async
    def touch_last_seen(self):
        self.last_seen_at = time.monotonic()
        User.objects.filter(pk=self.user.pk).update(last_seen=timezone.now())
