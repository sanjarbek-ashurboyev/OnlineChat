from phonenumber_field.phonenumber import to_python
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class LoginIPThrottle(AnonRateThrottle):
    """Login attempts per client IP."""
    scope = 'login_ip'


class LoginPhoneThrottle(SimpleRateThrottle):
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
