from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User


@database_sync_to_async
def user_from_token(raw_token):
    try:
        token = AccessToken(raw_token)
    except TokenError:
        return AnonymousUser()
    try:
        return User.objects.get(pk=token['user_id'])
    except (KeyError, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Resolve scope['user'] from a ?token= query parameter.

    The browser WebSocket API cannot set request headers, so the access token
    has to travel in the URL.
    """

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get('query_string', b'').decode())
        raw_token = query.get('token', [None])[0]
        scope['user'] = await user_from_token(raw_token) if raw_token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
