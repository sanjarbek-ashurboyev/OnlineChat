"""The load tester's pass/fail rules (Codex review #8). The tester itself needs a live server."""
from types import SimpleNamespace
from unittest import TestCase

from loadtest.verdict import pct, problems

PLAN = SimpleNamespace(max_error_rate=0.001, max_message_ms=300,
                       max_message_p99_ms=1000, max_poll_ms=300)


def healthy_row(**changes):
    row = {
        'users': 1000, 'connected': 1000,
        'messages_sent': 2000, 'lost_messages': 0,
        'message_p95_ms': 90, 'message_p99_ms': 200,
        'messages_to_online': 2000, 'undelivered': 0, 'delivery_p95_ms': 95,
        'polls': 1300, 'poll_errors': 0, 'poll_p95_ms': 40,
    }
    return {**row, **changes}


class VerdictTests(TestCase):
    def test_a_good_step_is_healthy(self):
        self.assertEqual(problems(healthy_row(), PLAN), [])

    def test_sends_with_no_echoes_fail(self):
        # The old tester called this healthy: no samples counted as 0 ms.
        row = healthy_row(messages_sent=10, message_p95_ms=None, message_p99_ms=None,
                          messages_to_online=10, delivery_p95_ms=None)
        self.assertIn('message p95: no measurements', problems(row, PLAN))
        self.assertIn('delivery p95: no measurements', problems(row, PLAN))

    def test_a_quiet_step_with_nothing_sent_is_not_a_failure(self):
        row = healthy_row(messages_sent=0, message_p95_ms=None, message_p99_ms=None,
                          messages_to_online=0, delivery_p95_ms=None)
        self.assertEqual(problems(row, PLAN), [])

    def test_the_plan_targets_are_the_limits(self):
        self.assertEqual(problems(healthy_row(message_p95_ms=301), PLAN), ['message p95 301ms > 300ms'])
        self.assertEqual(problems(healthy_row(message_p99_ms=1001), PLAN), ['message p99 1001ms > 1000ms'])
        self.assertEqual(problems(healthy_row(poll_p95_ms=301), PLAN), ['chat list p95 301ms > 300ms'])
        self.assertEqual(problems(healthy_row(delivery_p95_ms=301), PLAN), ['delivery p95 301ms > 300ms'])

    def test_errors_must_stay_under_one_in_a_thousand(self):
        # The plan says "errors < 0.1%", so exactly 0.1% fails (Codex audit L-01).
        self.assertEqual(problems(healthy_row(lost_messages=1), PLAN), [])
        self.assertEqual(problems(healthy_row(lost_messages=2), PLAN), ['2/2000 messages got no echo'])
        self.assertEqual(problems(healthy_row(undelivered=2), PLAN),
                         ['2/2000 messages never reached the recipient'])
        self.assertEqual(problems(healthy_row(connected=999), PLAN), ['1/1000 users not connected'])
        self.assertEqual(problems(healthy_row(poll_errors=2), PLAN), ['2/1302 chat list requests failed'])

    def test_a_zero_error_limit_still_passes_a_clean_step(self):
        self.assertEqual(problems(healthy_row(), SimpleNamespace(**{**vars(PLAN), 'max_error_rate': 0})), [])

    def test_percentiles(self):
        self.assertIsNone(pct([], 95))
        self.assertEqual(pct(list(range(1, 101)), 95), 96)
        self.assertEqual(pct([7], 99), 7)
