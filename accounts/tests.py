import shutil
import tempfile
import threading
import unittest
from datetime import timedelta
from io import BytesIO
from unittest import mock

import jwt
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from accounts.serializers import RegisterSerializer
from chats import presence
from chats.models import Block
from test_helpers import (
    PASSWORD,
    FakePresenceMixin,
    client_for,
    make_user,
    phone,
    token_for,
)


class RegisterTests(TestCase):
    URL = '/api/v1/auth/register/'

    def setUp(self):
        cache.clear()  # the register throttle counts in the cache

    def register(self, **overrides):
        data = {'phone_number': phone(1), 'password': PASSWORD, 'confirm_password': PASSWORD,
                'first_name': 'Ali'}
        return APIClient().post(self.URL, {**data, **overrides})

    def test_creates_a_user_who_can_log_in(self):
        self.assertEqual(self.register().status_code, 201)
        user = User.objects.get()
        self.assertEqual(str(user.phone_number), phone(1))
        self.assertTrue(user.check_password(PASSWORD))

    def test_mismatched_passwords_are_rejected(self):
        response = self.register(confirm_password='Different-pass1!')
        self.assertEqual(response.status_code, 400)
        self.assertIn('confirm_password', response.data)

    def test_weak_password_is_rejected(self):
        self.assertEqual(self.register(password='12345678', confirm_password='12345678').status_code, 400)

    def test_phone_number_can_only_register_once(self):
        self.register()
        self.assertEqual(self.register().status_code, 400)
        self.assertEqual(User.objects.count(), 1)

    def test_password_is_never_returned(self):
        self.assertNotIn('password', self.register().data)

    def test_a_password_like_the_first_name_is_rejected(self):
        # Codex audit M-17: the similarity validator needs the would-be user to compare against.
        response = self.register(first_name='Bahodirjon', password='Bahodirjon',
                                 confirm_password='Bahodirjon')
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

    def test_two_registrations_racing_for_one_number_give_a_400_not_a_500(self):
        # Codex audit M-18: both pass the uniqueness check before either saves.
        data = {'phone_number': phone(1), 'password': PASSWORD, 'confirm_password': PASSWORD,
                'first_name': 'Ali'}
        first, second = RegisterSerializer(data=data), RegisterSerializer(data=data)
        self.assertTrue(first.is_valid())
        self.assertTrue(second.is_valid())
        first.save()

        with self.assertRaises(ValidationError) as caught:
            second.save()
        self.assertIn('phone_number', caught.exception.detail)
        self.assertEqual(User.objects.count(), 1)


class LoginTests(TestCase):
    REFRESH_URL = '/api/v1/auth/token/refresh/'

    def setUp(self):
        self.user = make_user()

    def test_login_returns_a_jwt_pair(self):
        response = APIClient().post('/api/v1/auth/login/', {'phone_number': phone(1), 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'access', 'refresh'})

    def test_wrong_password_is_refused(self):
        response = APIClient().post('/api/v1/auth/login/', {'phone_number': phone(1), 'password': 'nope'})
        self.assertEqual(response.status_code, 401)

    def test_a_refresh_token_gets_a_working_access_token(self):
        tokens = APIClient().post('/api/v1/auth/login/',
                                  {'phone_number': phone(1), 'password': PASSWORD}).data
        response = APIClient().post(self.REFRESH_URL, {'refresh': tokens['refresh']})
        self.assertEqual(response.status_code, 200)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(client.get('/api/v1/auth/profile/').status_code, 200)

    def test_a_bad_refresh_token_is_refused(self):
        self.assertEqual(APIClient().post(self.REFRESH_URL, {'refresh': 'garbage'}).status_code, 401)

    def test_an_access_token_cannot_be_used_to_refresh(self):
        # Otherwise a short-lived access token could be renewed forever.
        response = APIClient().post(self.REFRESH_URL, {'refresh': token_for(self.user)})
        self.assertEqual(response.status_code, 401)

    def test_an_authenticated_request_records_last_seen(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_for(self.user)}')

        self.assertEqual(client.get('/api/v1/auth/profile/').status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_seen)


class RefreshRotationAndLogoutTests(TestCase):
    """T-07 (SEC-7): a refresh token works once, and logging out ends it on the server."""
    REFRESH_URL = '/api/v1/auth/token/refresh/'
    LOGOUT_URL = '/api/v1/auth/logout/'

    def setUp(self):
        cache.clear()  # refresh and logout are throttled
        self.addCleanup(cache.clear)
        self.user = make_user()
        self.tokens = APIClient().post('/api/v1/auth/login/',
                                       {'phone_number': phone(1), 'password': PASSWORD}).data

    def refresh(self, token):
        return APIClient().post(self.REFRESH_URL, {'refresh': token})

    def test_refreshing_returns_a_new_refresh_token_and_retires_the_old_one(self):
        renewed = self.refresh(self.tokens['refresh'])
        self.assertEqual(renewed.status_code, 200)
        self.assertIn('refresh', renewed.data)
        self.assertNotEqual(renewed.data['refresh'], self.tokens['refresh'])

        self.assertEqual(self.refresh(self.tokens['refresh']).status_code, 401, 'a stolen old token is useless')
        self.assertEqual(self.refresh(renewed.data['refresh']).status_code, 200)

    def test_after_logout_the_refresh_token_is_refused(self):
        response = APIClient().post(self.LOGOUT_URL, {'refresh': self.tokens['refresh']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh(self.tokens['refresh']).status_code, 401)

    def test_logout_needs_no_access_token(self):
        # The access token may have expired already; the refresh token is the proof.
        response = APIClient().post(self.LOGOUT_URL, {'refresh': self.tokens['refresh']})
        self.assertEqual(response.status_code, 200)

    def test_logout_with_a_bad_or_an_access_token_is_refused(self):
        self.assertEqual(APIClient().post(self.LOGOUT_URL, {'refresh': 'garbage'}).status_code, 401)
        self.assertEqual(APIClient().post(self.LOGOUT_URL, {'refresh': self.tokens['access']}).status_code, 401)

    def test_logout_ends_only_that_login(self):
        other = APIClient().post('/api/v1/auth/login/', {'phone_number': phone(1), 'password': PASSWORD}).data
        APIClient().post(self.LOGOUT_URL, {'refresh': self.tokens['refresh']})
        self.assertEqual(self.refresh(other['refresh']).status_code, 200, 'another device stays signed in')

    def test_logout_with_an_older_token_of_the_same_login_ends_it(self):
        # Codex review of #40: tab A renewed R0 -> R1; tab B still held R0 and signed out with it. That has to end
        # the login, or R1 keeps working after the user pressed "Log out".
        renewed = self.refresh(self.tokens['refresh']).data['refresh']
        response = APIClient().post(self.LOGOUT_URL, {'refresh': self.tokens['refresh']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh(renewed).status_code, 401)

    def test_a_token_from_before_login_sessions_is_refused(self):
        # Issued before this change: no `sid`, so no session can say it's still the current one. Sign in again.
        self.assertEqual(self.refresh(str(RefreshToken.for_user(self.user))).status_code, 401)


class ConcurrentRefreshTests(TransactionTestCase):
    """Codex review of #40: one refresh token, two requests at the same moment, must give one new token, not two."""
    REFRESH_URL = '/api/v1/auth/token/refresh/'

    def setUp(self):
        if connection.vendor != 'postgresql':
            raise unittest.SkipTest('two requests at once need a database that two threads can share')
        cache.clear()
        self.addCleanup(cache.clear)
        make_user()
        self.token = APIClient().post('/api/v1/auth/login/', {'phone_number': phone(1), 'password': PASSWORD}).data['refresh']

    def test_two_requests_with_one_token_get_one_new_token(self):
        # Hold both requests just after their token passed every check, so neither has spent it yet: the moment a
        # thief's copy and the real tab can both be in. Without the hold this race is real but rarely hit.
        both_checked = threading.Barrier(2)
        original = RefreshToken.access_token

        def access_token_once_both_are_checked(token):
            try:
                both_checked.wait(timeout=2)
            except threading.BrokenBarrierError:
                pass  # only one request got this far: nothing to line up
            return original.fget(token)

        statuses = []

        def redeem():
            try:
                statuses.append(APIClient().post(self.REFRESH_URL, {'refresh': self.token}).status_code)
            finally:
                connection.close()

        with mock.patch.object(RefreshToken, 'access_token', property(access_token_once_both_are_checked)):
            threads = [threading.Thread(target=redeem) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(sorted(statuses), [200, 401])


class AuthThrottleTests(TestCase):
    """SEC-3: login, registration and refresh are rate limited."""
    LOGIN = '/api/v1/auth/login/'

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)  # don't leave full counters for later tests

    def login(self, n, ip='10.0.0.1'):
        return APIClient().post(self.LOGIN, {'phone_number': phone(n), 'password': 'wrong'},
                                REMOTE_ADDR=ip)

    def test_one_phone_number_gets_5_logins_a_minute_from_any_ip(self):
        for _ in range(5):
            self.assertEqual(self.login(1).status_code, 401)
        self.assertEqual(self.login(1).status_code, 429)
        self.assertEqual(self.login(1, ip='10.0.0.2').status_code, 429)
        self.assertEqual(self.login(2).status_code, 401, 'other numbers are unaffected')

    def test_the_phone_limit_ignores_how_the_number_is_written(self):
        for _ in range(5):
            self.login(1)
        response = APIClient().post(self.LOGIN, {'phone_number': '90 123 45 01', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)

    def test_a_body_that_is_not_an_object_is_a_400_not_a_crash(self):
        response = APIClient().post(self.LOGIN, ['+998901234501'], format='json')
        self.assertEqual(response.status_code, 400)

    def test_one_ip_gets_20_logins_a_minute(self):
        for n in range(20):
            self.assertEqual(self.login(n).status_code, 401)
        self.assertEqual(self.login(20).status_code, 429)
        self.assertEqual(self.login(20, ip='10.0.0.2').status_code, 401, 'other IPs are unaffected')

    def test_one_ip_can_register_5_times_an_hour(self):
        def register(n, ip='10.0.0.1'):
            return APIClient().post('/api/v1/auth/register/', {
                'phone_number': phone(n), 'password': PASSWORD, 'confirm_password': PASSWORD,
                'first_name': 'Ali'}, REMOTE_ADDR=ip)

        for n in range(5):
            self.assertEqual(register(n).status_code, 201)
        self.assertEqual(register(5).status_code, 429)
        self.assertEqual(register(5, ip='10.0.0.2').status_code, 201)

    def test_a_forged_forwarded_for_header_does_not_reset_the_ip_limit(self):
        # Codex audit H-02: with NUM_PROXIES unset, DRF used the client's own X-Forwarded-For as its IP.
        def login(n):
            return APIClient().post(self.LOGIN, {'phone_number': phone(n), 'password': 'wrong'},
                                    REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR=f'203.0.113.{n}')

        for n in range(20):
            self.assertEqual(login(n).status_code, 401)
        self.assertEqual(login(20).status_code, 429)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1})
    def test_behind_one_proxy_the_client_ip_is_the_one_the_proxy_added(self):
        def login(n, forwarded):
            # Every request reaches Django from the proxy; it appends the real client IP to the header.
            return APIClient().post(self.LOGIN, {'phone_number': phone(n), 'password': 'wrong'},
                                    REMOTE_ADDR='10.0.0.9', HTTP_X_FORWARDED_FOR=forwarded)

        for n in range(20):
            # The client's own forged entry comes first and is ignored.
            self.assertEqual(login(n, f'198.51.100.{n}, 203.0.113.1').status_code, 401)
        self.assertEqual(login(20, '203.0.113.1').status_code, 429)
        self.assertEqual(login(20, '203.0.113.2').status_code, 401, 'other clients are unaffected')

    def test_a_signed_in_client_still_counts_against_the_registration_ip_limit(self):
        # Codex audit H-03: a token used to switch the counter from the IP to the user.
        def register(n, **headers):
            return APIClient().post('/api/v1/auth/register/', {
                'phone_number': phone(n), 'password': PASSWORD, 'confirm_password': PASSWORD,
                'first_name': 'Ali'}, REMOTE_ADDR='10.0.0.1', **headers)

        for n in range(5):
            self.assertEqual(register(n).status_code, 201)
        token = token_for(User.objects.first())
        self.assertEqual(register(5, HTTP_AUTHORIZATION=f'Bearer {token}').status_code, 429)

    def test_login_and_refresh_still_answer_when_the_throttle_cache_is_down(self):
        # Codex audit M-19; the plan says throttles fail open (docs/scaling/02-plan.md, T-21).
        down = mock.Mock(**{'get.side_effect': RedisConnectionError, 'set.side_effect': RedisConnectionError})
        with mock.patch.object(SimpleRateThrottle, 'cache', down), \
                self.assertLogs('accounts.throttles', 'WARNING') as logs:
            self.assertEqual(self.login(1).status_code, 401)
            response = APIClient().post('/api/v1/auth/token/refresh/', {'refresh': 'garbage'})
            self.assertEqual(response.status_code, 401)
        down.get.assert_called()
        self.assertEqual(len(logs.records), 3)  # login IP, login phone, refresh: each outage is visible

    def test_one_ip_can_refresh_30_times_a_minute(self):
        def refresh():
            return APIClient().post('/api/v1/auth/token/refresh/', {'refresh': 'garbage'},
                                    REMOTE_ADDR='10.0.0.1')

        for _ in range(30):
            self.assertEqual(refresh().status_code, 401)
        self.assertEqual(refresh().status_code, 429)


class ProfileTests(TestCase):
    URL = '/api/v1/auth/profile/'

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(self.URL).status_code, 401)

    def test_name_can_change_but_phone_number_cannot(self):
        user = make_user()
        response = client_for(user).patch(self.URL, {'first_name': 'Vali', 'phone_number': phone(9)})

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual((user.first_name, str(user.phone_number)), ('Vali', phone(1)))


def png(width=1, height=1, extra_bytes=0):
    """A valid PNG; extra_bytes of junk after it still pass Pillow's check."""
    buffer = BytesIO()
    Image.new('RGB', (width, height)).save(buffer, 'PNG')
    return SimpleUploadedFile('face.png', buffer.getvalue() + b'\0' * extra_bytes, content_type='image/png')


class AvatarTests(TestCase):
    """Codex audit M-15 (size limits) and M-16 (old files left behind)."""
    URL = '/api/v1/auth/profile/'

    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = make_user()
        self.client = client_for(self.user)

    def upload(self, file):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.patch(self.URL, {'avatar': file}, format='multipart')

    def stored(self):
        return default_storage.listdir('avatars')[1] if default_storage.exists('avatars') else []

    def test_a_small_photo_is_saved(self):
        self.assertEqual(self.upload(png(64, 64)).status_code, 200)
        self.assertEqual(len(self.stored()), 1)

    def test_a_file_over_2_mib_is_rejected(self):
        # The audit's case: a 1-pixel PNG with megabytes of junk after it passed.
        response = self.upload(png(extra_bytes=2 * 1024 * 1024))
        self.assertEqual(response.status_code, 400)
        self.assertIn('2 MiB', str(response.data['avatar']))
        self.assertEqual(self.stored(), [])

    def test_more_than_4096_pixels_on_a_side_is_rejected(self):
        for width, height in ((4097, 1), (1, 4097)):
            with self.subTest(f'{width}x{height}'):
                response = self.upload(png(width, height))
                self.assertEqual(response.status_code, 400)
                self.assertIn('4096', str(response.data['avatar']))

    def test_replacing_the_photo_deletes_the_old_file(self):
        self.upload(png())
        self.upload(png(2, 2))
        self.user.refresh_from_db()
        self.assertEqual(self.stored(), [self.user.avatar.name.split('/')[-1]])

    def test_removing_the_photo_deletes_the_file(self):
        self.upload(png())
        self.assertEqual(self.upload('').status_code, 200)
        self.assertEqual(self.stored(), [])

    def test_deleting_the_account_deletes_the_file(self):
        self.upload(png())
        with self.captureOnCommitCallbacks(execute=True):
            User.objects.filter(pk=self.user.pk).delete()
        self.assertEqual(self.stored(), [])

    def test_a_file_still_used_by_another_account_is_kept(self):
        self.upload(png())
        self.user.refresh_from_db()
        make_user(2, avatar=self.user.avatar.name)
        self.upload(png(2, 2))
        self.assertEqual(len(self.stored()), 2)

    def test_the_old_file_is_deleted_only_once_the_change_commits(self):
        self.upload(png())
        self.user.refresh_from_db()
        old = self.user.avatar.name
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.user.avatar = 'avatars/other.png'
            self.user.save()
        # Until the commit it may still be rolled back, so the deletion waits in the queue.
        self.assertEqual(len(callbacks), 1)
        self.assertTrue(default_storage.exists(old))


class PublicUserTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me = make_user(1)
        self.other = make_user(2)

    def url(self):
        return f'/api/v1/users/{self.other.id}/'

    def test_shows_whether_the_user_is_online(self):
        self.assertFalse(client_for(self.me).get(self.url()).data['is_online'])
        presence.mark_online(self.other.id, 'some-channel')
        self.assertTrue(client_for(self.me).get(self.url()).data['is_online'])

    def test_someone_who_blocked_you_is_hidden(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(client_for(self.me).get(self.url()).status_code, 404)

    def test_profiles_by_id_are_limited_to_120_a_minute(self):
        # SEC-4: ids are sequential, so this is how a scraper would walk every user.
        cache.clear()
        self.addCleanup(cache.clear)
        client = client_for(self.me)
        for _ in range(120):
            self.assertEqual(client.get(self.url()).status_code, 200)
        self.assertEqual(client.get(self.url()).status_code, 429)
        self.assertEqual(client_for(self.other).get(f'/api/v1/users/{self.me.id}/').status_code, 200,
                         'other users are unaffected')


class SigningKeyTests(SimpleTestCase):
    """SEC-1: tokens must be signed with this environment's key and no other."""

    def forge(self, key):
        now = timezone.now()
        claims = {**AccessToken().payload, 'user_id': '1', 'iat': now, 'exp': now + timedelta(minutes=5)}
        return jwt.encode(claims, key, algorithm='HS256')

    def test_token_signed_with_our_key_is_accepted(self):
        AccessToken(self.forge(settings.SECRET_KEY))

    def test_token_signed_with_another_key_is_rejected(self):
        with self.assertRaises(TokenError):
            AccessToken(self.forge('a-key-somebody-else-knows'))
