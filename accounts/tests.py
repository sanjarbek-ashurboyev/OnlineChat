from datetime import timedelta

import jwt
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
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


class UserLookupTests(FakePresenceMixin, TestCase):
    URL = '/api/v1/users/lookup/'

    def setUp(self):
        super().setUp()
        cache.clear()  # the lookup throttle counts in the cache
        self.me = make_user(1)
        self.other = make_user(2)

    def lookup(self, number, client=None):
        return (client or client_for(self.me)).get(self.URL, {'phone_number': number})

    def test_finds_a_user_by_local_or_international_number(self):
        for number in (phone(2), '90 123 45 02', '901234502'):
            with self.subTest(number):
                response = self.lookup(number)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['id'], self.other.id)

    def test_does_not_reveal_the_phone_number(self):
        self.assertNotIn('phone_number', self.lookup(phone(2)).data)

    def test_you_cannot_look_yourself_up(self):
        self.assertEqual(self.lookup(phone(1)).status_code, 404)

    def test_someone_who_blocked_you_looks_like_a_missing_user(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.lookup(phone(2)).status_code, 404)

    def test_invalid_or_missing_number_is_a_400(self):
        self.assertEqual(self.lookup('12345').status_code, 400)
        self.assertEqual(client_for(self.me).get(self.URL).status_code, 400)

    def test_lookups_are_limited_to_20_an_hour(self):
        # Phone-number lookup is how scrapers would enumerate accounts.
        client = client_for(self.me)
        for _ in range(20):
            self.assertEqual(self.lookup(phone(2), client).status_code, 200)
        self.assertEqual(self.lookup(phone(2), client).status_code, 429)


class PublicUserTests(FakePresenceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.me = make_user(1)
        self.other = make_user(2)

    def url(self):
        return f'/api/v1/users/{self.other.id}/'

    def test_shows_whether_the_user_is_online(self):
        self.assertFalse(client_for(self.me).get(self.url()).data['is_online'])
        self.redis.sadd(f'presence:{self.other.id}', 'some-channel')
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
