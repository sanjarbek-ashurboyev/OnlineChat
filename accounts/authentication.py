from datetime import timedelta

from django.utils import timezone
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.models import User

TOUCH_INTERVAL = timedelta(minutes=1)


class LastSeenJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _ = result
            now = timezone.now()
            if user.last_seen is None or now - user.last_seen > TOUCH_INTERVAL:
                User.objects.filter(pk=user.pk).update(last_seen=now)
        return result


class LastSeenJWTScheme(SimpleJWTScheme):
    """Tells the OpenAPI schema our authenticator is SimpleJWT's bearer token (M-20).
    drf-spectacular matches the exact class, so a subclass needs its own entry."""
    target_class = LastSeenJWTAuthentication
