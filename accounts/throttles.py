import logging

from phonenumber_field.phonenumber import to_python
from redis.exceptions import RedisError
from rest_framework import throttling

logger = logging.getLogger(__name__)


class FailOpenMixin:
    """If Redis (the throttle cache) is down, let the request through instead of answering 500.

    A Redis outage must not take login down (docs/scaling/02-plan.md, Decision 0.2 and T-21).
    """

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except RedisError as exc:
            logger.warning('Throttle cache unavailable, %s not applied: %r', type(self).__name__, exc)
            return True


class ScopedRateThrottle(FailOpenMixin, throttling.ScopedRateThrottle):
    """DRF's: per user when signed in, per IP otherwise."""


class LoginIPThrottle(FailOpenMixin, throttling.AnonRateThrottle):
    """Login attempts per client IP."""
    scope = 'login_ip'


class LoginPhoneThrottle(FailOpenMixin, throttling.SimpleRateThrottle):
    """Login attempts per phone number, from any IP: stops password guessing on one account."""
    scope = 'login_phone'

    def get_cache_key(self, request, view):
        raw = request.data.get('phone_number') if hasattr(request.data, 'get') else None
        if not isinstance(raw, str):
            return None
        # Normalise, so '90 123 45 01' and '+998901234501' share one counter.
        number = to_python(raw, region='UZ')
        if not number or not number.is_valid():
            return None  # can't match an account; the IP limit still applies
        return self.cache_format % {'scope': self.scope, 'ident': number.as_e164}


class RegisterIPThrottle(FailOpenMixin, throttling.SimpleRateThrottle):
    """Registrations per client IP, signed in or not: a token must not buy a fresh allowance."""
    scope = 'register_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
