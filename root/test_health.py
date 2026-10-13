"""/readyz: can this process serve traffic? Its database and Redis must both answer (T-21, T-12 step 3)."""
from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

URL = '/readyz'


@mock.patch('chats.presence.client')
class ReadinessTests(SimpleTestCase):
    databases = {'default'}

    def test_ready_when_the_database_and_redis_answer(self, redis_client):
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'database': 'ok', 'redis': 'ok'})
        redis_client.return_value.ping.assert_called_once()

    def test_not_ready_without_redis(self, redis_client):
        redis_client.return_value.ping.side_effect = RedisConnectionError('Error 61 connecting to localhost:6390.')
        with self.assertLogs('root.health', 'ERROR'):
            response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'database': 'ok', 'redis': 'error'}, 'no error details in the answer')

    def test_not_ready_without_the_database(self, redis_client):
        with mock.patch('root.health.connection') as connection, self.assertLogs('root.health', 'ERROR'):
            connection.cursor.side_effect = OperationalError('connection refused')
            response = self.client.get(URL)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'database': 'error', 'redis': 'ok'})

    def test_needs_no_token(self, redis_client):
        self.assertEqual(self.client.get(URL, HTTP_AUTHORIZATION='Bearer nonsense').status_code, 200)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_a_plain_http_probe_is_not_redirected(self, redis_client):
        # A load balancer probes the app directly, over plain HTTP; a 301 would read as "down".
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/chats/').status_code, 301, 'everything else still redirects')
