from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User


@database_sync_to_async
def user_from_token(raw_token):
    """The token's user and its expiry (Unix time), or (AnonymousUser, None)."""
    try:
        token = AccessToken(raw_token)
    except TokenError:
        return AnonymousUser(), None
    try:
        # is_active: a disabled account's unexpired token must stop working, as it does for REST.
        return User.objects.get(pk=token['user_id'], is_active=True), token['exp']
    except (KeyError, User.DoesNotExist):
        return AnonymousUser(), None


class JWTAuthMiddleware(BaseMiddleware):
    """Resolve scope['user'] from a ?token= query parameter.

    The browser WebSocket API cannot set request headers, so the access token
    has to travel in the URL.
    """

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        raw_token = query.get('token', [None])[0]
        # The consumer closes the socket at token_exp: the token's rights end then (Codex audit H-01).
        scope['user'], scope['token_exp'] = (await user_from_token(raw_token) if raw_token
                                             else (AnonymousUser(), None))
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
