import time


class TokenBucket:
    """Allows short bursts, caps the sustained rate (docs/scaling/02-plan.md, Decision 0.2).

    Holds up to `burst` tokens and refills `rate` tokens per second. Each action
    spends one; with none left, the action is refused. Not shared between
    processes: one bucket per socket.
    """

    def __init__(self, rate: float, burst: int):
        self.rate, self.burst = rate, burst
        self.tokens, self.updated = float(burst), time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        # Refill for the time that passed, never above the bucket size.
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
