"""Create paired users and chats for loadtest/run.py and write their tokens.

Users are created two at a time, each pair sharing one chat, so every
simulated client has somebody to talk to. Re-running replaces the previous
load test users (and, by cascade, their chats and messages).
"""

import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from chats.models import Chat, Message

# +998 00 is not a real Uzbek range: registration rejects these numbers as invalid,
# so no real user can hold one. The marker is a second check.
PHONE_PREFIX = '+998000'
MARKER = 'loadtest'


def loadtest_users():
    return User.objects.filter(phone_number__startswith=PHONE_PREFIX,
                               first_name=MARKER)


class Command(BaseCommand):
    help = 'Create paired users and chats for loadtest/run.py and write their access tokens.'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int, default=2000,
                            help='How many users to create (rounded up to even).')
        parser.add_argument('--messages', type=int, default=20,
                            help='History messages per chat, so the chat list query has real work.')
        parser.add_argument('--token-hours', type=float, default=4,
                            help='Access token lifetime; must outlast the whole test.')
        parser.add_argument('--out', default='loadtest/tokens.json')
        parser.add_argument('--delete', action='store_true',
                            help='Only remove existing load test users, then exit.')
        parser.add_argument('--force', action='store_true',
                            help='Allow running with DEBUG off.')

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts['force']:
            raise CommandError('DEBUG is off: this looks like production. Pass --force if it is not.')

        if opts['delete']:
            deleted, _ = loadtest_users().delete()
            self.stdout.write(f'Removed {deleted} load test rows.')
            return

        # Check everything before deleting anything.
        count = opts['users'] + opts['users'] % 2
        if not 2 <= count <= 999_999:
            raise CommandError('--users must be between 2 and 999999.')
        if opts['messages'] < 0:
            raise CommandError('--messages must be 0 or more.')
        if opts['token_hours'] <= 0:
            raise CommandError('--token-hours must be more than 0.')

        # Tokens are minted directly, so nobody logs in and the hash is never checked.
        password = make_password(None)
        # One transaction: if creating the new users fails, the old ones come back.
        with transaction.atomic():
            loadtest_users().delete()
            users = User.objects.bulk_create(
                [User(phone_number=f'{PHONE_PREFIX}{i:06d}', first_name=MARKER,
                      password=password) for i in range(count)],
                batch_size=2000,
            )
            chats = Chat.objects.bulk_create(
                [Chat(user1=a, user2=b) for a, b in zip(users[::2], users[1::2], strict=True)],
                batch_size=2000,
            )
            Message.objects.bulk_create(
                (Message(chat=chat, text=f'history {n}', is_read=True,
                         sender_id=(chat.user1_id, chat.user2_id)[n % 2])
                 for chat in chats for n in range(opts['messages'])),
                batch_size=5000,
            )

        lifetime = timedelta(hours=opts['token_hours'])
        rows = []
        for chat in chats:
            for user in (chat.user1, chat.user2):
                token = AccessToken.for_user(user)
                token.set_exp(lifetime=lifetime)
                rows.append({'user_id': user.pk, 'chat_id': chat.pk, 'token': str(token)})

        out = Path(opts['out'])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows))
        self.stdout.write(self.style.SUCCESS(
            f'Created {count} users, {len(chats)} chats, '
            f'{len(chats) * opts["messages"]} messages. Tokens in {out}.'))
