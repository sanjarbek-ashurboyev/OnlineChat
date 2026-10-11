"""Pass/fail rules for one load test step. No aiohttp here, so the test suite can import it."""


def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p / 100))]


def problems(row, limits):
    """What's wrong with a step, as readable strings. Empty means healthy.

    `limits` has max_error_rate, max_message_ms, max_message_p99_ms and max_poll_ms
    (docs/scaling/02-plan.md: p95 <= 300 ms, p99 <= 1 s, REST p95 <= 300 ms, errors < 0.1%).
    """
    found = []
    max_errors = limits.max_error_rate

    def too_many(bad, total, what):
        # The error rate must stay *under* the limit, so reaching it fails.
        if bad and bad / total >= max_errors:
            found.append(f'{bad}/{total} {what}')

    too_many(row['users'] - row['connected'], row['users'], 'users not connected')
    too_many(row['lost_messages'], row['messages_sent'], 'messages got no echo')
    too_many(row['undelivered'], row['messages_to_online'], 'messages never reached the recipient')
    too_many(row['poll_errors'], row['polls'] + row['poll_errors'], 'chat list requests failed')

    # No measurement is a failure, never a pass: zero echoes must not read as 0 ms.
    for name, key, count, limit in (
        ('message p95', 'message_p95_ms', row['messages_sent'], limits.max_message_ms),
        ('message p99', 'message_p99_ms', row['messages_sent'], limits.max_message_p99_ms),
        ('delivery p95', 'delivery_p95_ms', row['messages_to_online'], limits.max_message_ms),
        ('chat list p95', 'poll_p95_ms', row['polls'] + row['poll_errors'], limits.max_poll_ms),
    ):
        value = row[key]
        if count and value is None:
            found.append(f'{name}: no measurements')
        elif value is not None and value > limit:
            found.append(f'{name} {value:.0f}ms > {limit:.0f}ms')
    return found
