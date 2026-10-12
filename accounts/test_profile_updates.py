"""PR #34: profile updates must not lose files or fail after a committed save."""
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import mock

from django.core.files.storage import default_storage
from django.db import close_old_connections
from django.db.models.signals import pre_save
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)

from accounts.models import User
from accounts.serializers import ProfileSerializer
from accounts.tests import png
from test_helpers import client_for, make_user


class AvatarStorageMixin:
    def setUp(self):
        super().setUp()
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = make_user()

    def update(self, user, **data):
        serializer = ProfileSerializer(user, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def files(self):
        return sorted(default_storage.listdir('avatars')[1])


class ProfileUpdateTests(AvatarStorageMixin, TestCase):
    def test_a_delayed_name_update_keeps_the_new_avatar(self):
        self.update(self.user, avatar=png())
        stale = User.objects.get(pk=self.user.pk)  # request B authenticated before A uploaded
        with self.captureOnCommitCallbacks(execute=True):
            saved = self.update(self.user, avatar=png(2, 2))
        new_name = saved.avatar.name
        with self.captureOnCommitCallbacks(execute=True):
            response = client_for(stale).patch('/api/v1/auth/profile/', {'first_name': 'Renamed'})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar.name, new_name)
        self.assertTrue(default_storage.exists(new_name))
        self.assertEqual(self.files(), [new_name.split('/')[-1]])

    def test_avatar_cleanup_failure_does_not_fail_a_saved_profile(self):
        self.update(self.user, avatar=png())
        with mock.patch.object(User.avatar.field.storage, 'delete', side_effect=OSError('storage unavailable')) as delete:
            with self.assertLogs('accounts.signals', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    response = client_for(self.user).patch('/api/v1/auth/profile/', {'avatar': png(2, 2)}, format='multipart')
            delete.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(default_storage.exists(self.user.avatar.name))


class ConcurrentAvatarTests(AvatarStorageMixin, TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_overlapping_uploads_leave_only_the_current_avatar(self):
        self.update(self.user, avatar=png())
        first_paused, second_started, release_first = Event(), Event(), Event()

        def pause_first(sender, instance, **kwargs):
            if instance.first_name == 'First upload':
                first_paused.set()
                if not release_first.wait(5):
                    raise AssertionError('first upload was never released')

        pre_save.connect(pause_first, sender=User, weak=False)
        self.addCleanup(pre_save.disconnect, pause_first, sender=User)

        def upload(name, size):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                if name == 'Second upload':
                    second_started.set()
                return self.update(user, first_name=name, avatar=png(size, size)).avatar.name
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(upload, 'First upload', 2)
            try:
                self.assertTrue(first_paused.wait(5))
                second = pool.submit(upload, 'Second upload', 3)
                self.assertTrue(second_started.wait(5))
                # Old code can finish B while A is paused after reading the old filename.
                # Fixed code blocks B on A's row lock. Either way, release A after this window.
                try:
                    second.result(timeout=0.5)
                except TimeoutError:
                    pass
            finally:
                release_first.set()
            first.result(timeout=5)
            second.result(timeout=5)
        self.user.refresh_from_db()
        self.assertEqual(self.files(), [self.user.avatar.name.split('/')[-1]])
        self.assertTrue(default_storage.exists(self.user.avatar.name))
