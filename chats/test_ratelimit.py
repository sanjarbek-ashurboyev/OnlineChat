from unittest import mock

from django.test import SimpleTestCase

from chats.ratelimit import TokenBucket


class TokenBucketTests(SimpleTestCase):
    def setUp(self):
        self.now = 1000.0
        patcher = mock.patch('chats.ratelimit.time.monotonic', lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_burst_of_20_lets_10_through(self):
        bucket = TokenBucket(rate=1, burst=10)
        self.assertEqual(sum(bucket.take() for _ in range(20)), 10)

    def test_it_refills_at_the_rate(self):
        bucket = TokenBucket(rate=1, burst=10)
        for _ in range(10):
            bucket.take()
        self.assertFalse(bucket.take())

        self.now += 1
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())

    def test_it_never_holds_more_than_the_burst(self):
        bucket = TokenBucket(rate=1, burst=10)
        self.now += 3600  # an hour idle
        self.assertEqual(sum(bucket.take() for _ in range(20)), 10)
