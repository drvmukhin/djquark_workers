"""
Django settings for testing djquark-workers.
"""

SECRET_KEY = 'test-secret-key-for-djquark-workers'

DEBUG = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'djquark_workers',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Redis configuration for tests
QUARK_WORKERS_REDIS_URL = 'redis://localhost:6379/15'  # Use DB 15 for tests

QUARK_WORKERS_CONFIG = {
    'ENABLED': True,
    'HEARTBEAT_INTERVAL': 5,
    'HEARTBEAT_TTL': 10,
    'REDIS_PREFIX': 'test:quark:workers',
    'LOGGING_PREFIX': 'test:quark:logging',
    'ADMIN_PERMISSION': 'superuser',
}

QUARK_WORKERS_LOGGERS = [
    ('', 'Root Logger', 'root'),
    ('django', 'Django Core', 'django'),
    ('testapp', 'Test Application', 'application'),
]

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

ROOT_URLCONF = 'tests.urls'

USE_TZ = True

