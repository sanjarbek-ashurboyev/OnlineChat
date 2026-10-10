import os
from os.path import join
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')



DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('DJANGO_SECRET_KEY must be set when DEBUG is off.')
    SECRET_KEY = 'django-insecure-local-development-only'

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
                        if o.strip()]

if not DEBUG:
    # TLS ends at the reverse proxy, which must set X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SSL_REDIRECT', 'True') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start short and raise once HTTPS is known to work: browsers cache HSTS.
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('DJANGO_HSTS_INCLUDE_SUBDOMAINS') == 'True'
    SECURE_HSTS_PRELOAD = os.environ.get('DJANGO_HSTS_PRELOAD') == 'True'
    # Off by choice until every subdomain is HTTPS-only; check --deploy would otherwise flag them.
    SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']



INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'chats',
    'accounts',
    'rest_framework',
    'drf_spectacular',
    'rest_framework_simplejwt',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'root.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'root.wsgi.application'
ASGI_APPLICATION = 'root.asgi.application'

REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [REDIS_URL]},
    },
}

# Shared across processes, so throttle counters survive a restart and are not
# per-worker the way the local-memory default is.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'{REDIS_URL}/1',
    },
}



DATABASES = {
      'default': {
          'ENGINE': 'django.db.backends.postgresql',
          'NAME': os.environ['DB_NAME'],
          'USER': os.environ['DB_USER'],
          'PASSWORD': os.environ['DB_PASSWORD'],
          'HOST': os.environ.get('DB_HOST', 'localhost'),
          'PORT': os.environ.get('DB_PORT', '5432'),
      }
}



AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]



LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Tashkent'

USE_I18N = True

USE_TZ = True



STATIC_URL = 'static/'
STATIC_ROOT = join(BASE_DIR, 'static')
# Source files live here; STATIC_ROOT above is collectstatic's output.
STATICFILES_DIRS = [BASE_DIR / 'assets']

MEDIA_URL = 'media/'
MEDIA_ROOT = join(BASE_DIR, 'media')

AUTH_USER_MODEL = 'accounts.User'



MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}


REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated"
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'accounts.authentication.LastSeenJWTAuthentication',
    ),
    # Anonymous scopes count per IP, signed-in ones per user (docs/scaling/02-plan.md, Decision 0.2).
    'DEFAULT_THROTTLE_RATES': {
        'user_lookup': '20/hour',
        'login_ip': '20/min',
        'login_phone': '5/min',
        'register_ip': '5/hour',
        'refresh': '30/min',
        'profile_read': '120/min',
        'chat_create': '30/hour',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,

}


SPECTACULAR_SETTINGS = {
    'TITLE': 'Online Chat API',
    'DESCRIPTION': 'Your project description',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}