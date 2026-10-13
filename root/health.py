import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe

from chats import presence

logger = logging.getLogger(__name__)


@require_safe
def readyz(request):
    """200 when this process can serve: Postgres and Redis both answer. 503 otherwise, so a load balancer
    stops sending it traffic. Says which one failed, never why: the reason goes to the log."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception:
        logger.exception('readyz: database check failed')
        checks['database'] = 'error'
    try:
        # One server holds the channel layer, the cache and presence; any client reaches it.
        presence.client().ping()
        checks['redis'] = 'ok'
    except Exception:
        logger.exception('readyz: Redis check failed')
        checks['redis'] = 'error'
    ready = all(value == 'ok' for value in checks.values())
    return JsonResponse(checks, status=200 if ready else 503)
