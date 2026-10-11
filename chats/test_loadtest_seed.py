"""loadtest_seed must never delete a real account (Codex audit H-05)."""
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from chats.management.commands.loadtest_seed import MARKER, PHONE_PREFIX, loadtest_users
from chats.models import Chat
from test_helpers import PASSWORD


class LoadtestSeedTests(TestCase):
    def setUp(self):
        out_dir = tempfile.TemporaryDirectory()
        self.addCleanup(out_dir.cleanup)
        self.out = str(Path(out_dir.name) / 'tokens.json')

    def seed(self, **opts):
        opts = {'force': True, 'out': self.out, 'messages': 0, **opts}
        call_command('loadtest_seed', stdout=mock.MagicMock(), **opts)

    def test_a_real_user_called_loadtest_is_never_deleted(self):
        # +998 99 0xx xx xx is a real Uzbek mobile range: the old prefix matched this person.
        real = User.objects.create_user(phone_number='+998990000001', password=PASSWORD, first_name=MARKER)

        self.seed(delete=True)
        self.seed(users=2)

        self.assertTrue(User.objects.filter(pk=real.pk).exists())

    def test_seed_numbers_can_never_be_registered(self):
        cache.clear()  # the register throttle counts in the cache
        response = APIClient().post('/api/v1/auth/register/', {
            'phone_number': f'{PHONE_PREFIX}000001', 'password': PASSWORD,
            'confirm_password': PASSWORD, 'first_name': MARKER})

        self.assertEqual(response.status_code, 400)
        self.assertIn('phone_number', response.data)

    def test_bad_arguments_change_nothing(self):
        self.seed(users=2)
        for bad in ({'users': 0}, {'users': 1_000_000}, {'messages': -1}, {'token_hours': 0}):
            with self.subTest(**bad):
                with self.assertRaises(CommandError):
                    self.seed(**bad)
                self.assertEqual(loadtest_users().count(), 2)

    def test_a_failed_reseed_keeps_the_previous_users(self):
        self.seed(users=2)
        with mock.patch.object(Chat.objects, 'bulk_create', side_effect=RuntimeError), \
                self.assertRaises(RuntimeError):
            self.seed(users=4)

        self.assertEqual(loadtest_users().count(), 2)

    def test_reseeding_replaces_the_previous_users(self):
        self.seed(users=2)
        self.seed(users=4)

        self.assertEqual(loadtest_users().count(), 4)
        self.assertEqual(Chat.objects.count(), 2)
