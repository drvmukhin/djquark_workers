"""
Configuration settings for djquark-workers.

All settings are accessed via the `settings` object which reads from
Django settings with the QUARK_WORKERS_ prefix.
"""

from typing import List, Tuple, Optional, Any, Dict


class QuarkWorkersSettings:
    """
    Lazy settings object that reads from Django settings.

    All settings use the QUARK_WORKERS_ prefix in Django settings.
    """

    # Default values
    DEFAULTS = {
        'ENABLED': True,
        'HEARTBEAT_INTERVAL': 30,
        'HEARTBEAT_TTL': 60,
        'REDIS_PREFIX': 'quark:workers',
        'LOGGING_PREFIX': 'quark:logging',
        'ADMIN_PERMISSION': 'superuser',  # 'superuser', 'staff', or permission string
    }

    # Default loggers if none specified
    DEFAULT_LOGGERS: List[Tuple[str, str, str]] = [
        ('', 'Root Logger', 'root'),
        ('django', 'Django Core', 'django'),
        ('django.request', 'Django Requests', 'django'),
        ('django.security', 'Django Security', 'django'),
        ('django.db.backends', 'Database Queries', 'django'),
    ]

    # Log level choices for UI
    LOG_LEVELS: List[Tuple[str, str]] = [
        ('DEBUG', 'DEBUG - Detailed diagnostic info'),
        ('INFO', 'INFO - General operational info'),
        ('WARNING', 'WARNING - Something unexpected'),
        ('ERROR', 'ERROR - Serious problem'),
        ('CRITICAL', 'CRITICAL - Program may not continue'),
    ]

    def __init__(self):
        self._cached_settings = None

    def _get_django_settings(self) -> Dict[str, Any]:
        """Load settings from Django settings."""
        if self._cached_settings is not None:
            return self._cached_settings

        from django.conf import settings as django_settings

        # Get config dict
        config = getattr(django_settings, 'QUARK_WORKERS_CONFIG', {})

        # Merge with defaults
        self._cached_settings = {**self.DEFAULTS, **config}

        return self._cached_settings

    @property
    def ENABLED(self) -> bool:
        """Whether worker registration is enabled."""
        return self._get_django_settings().get('ENABLED', True)

    @property
    def HEARTBEAT_INTERVAL(self) -> int:
        """Seconds between heartbeats."""
        return self._get_django_settings().get('HEARTBEAT_INTERVAL', 30)

    @property
    def HEARTBEAT_TTL(self) -> int:
        """Seconds before worker considered dead."""
        return self._get_django_settings().get('HEARTBEAT_TTL', 60)

    @property
    def REDIS_PREFIX(self) -> str:
        """Redis key prefix for worker data."""
        return self._get_django_settings().get('REDIS_PREFIX', 'quark:workers')

    @property
    def LOGGING_PREFIX(self) -> str:
        """Redis key prefix for logging data."""
        return self._get_django_settings().get('LOGGING_PREFIX', 'quark:logging')

    @property
    def ADMIN_PERMISSION(self) -> str:
        """Required permission for admin panel access."""
        return self._get_django_settings().get('ADMIN_PERMISSION', 'superuser')

    @property
    def REDIS_URL(self) -> Optional[str]:
        """
        Get Redis URL for connections.

        Checks in order:
        1. QUARK_WORKERS_REDIS_URL
        2. QUARK_WORKERS_REDIS_CACHE (uses Django cache backend URL)
        3. REDIS_URL (fallback)
        4. Default localhost
        """
        from django.conf import settings as django_settings

        # Direct URL
        url = getattr(django_settings, 'QUARK_WORKERS_REDIS_URL', None)
        if url:
            return url

        # From cache backend
        cache_name = getattr(django_settings, 'QUARK_WORKERS_REDIS_CACHE', None)
        if cache_name:
            caches = getattr(django_settings, 'CACHES', {})
            cache_config = caches.get(cache_name, {})
            location = cache_config.get('LOCATION', '')
            if location:
                return location

        # Fallback to REDIS_URL
        url = getattr(django_settings, 'REDIS_URL', None)
        if url:
            return url

        # Default
        return 'redis://localhost:6379/0'

    @property
    def CONFIGURABLE_LOGGERS(self) -> List[Tuple[str, str, str]]:
        """
        Get list of configurable loggers.

        Format: List of (logger_name, display_name, category) tuples.
        Categories: 'application', 'django', 'infrastructure', 'root'
        """
        from django.conf import settings as django_settings

        loggers = getattr(django_settings, 'QUARK_WORKERS_LOGGERS', None)

        if loggers is None:
            return self.DEFAULT_LOGGERS

        # Normalize format
        result = []
        for item in loggers:
            if isinstance(item, (list, tuple)):
                if len(item) >= 3:
                    result.append((item[0], item[1], item[2]))
                elif len(item) == 2:
                    result.append((item[0], item[1], 'application'))
                else:
                    result.append((item[0], self._make_display_name(item[0]), 'application'))
            else:
                # String format - auto-generate display name and category
                name = str(item)
                display = self._make_display_name(name)
                category = self._detect_category(name)
                result.append((name, display, category))

        return result

    @staticmethod
    def _make_display_name(logger_name: str) -> str:
        """Generate a display name from a logger name."""
        if not logger_name:
            return 'Root Logger'
        # Convert 'myapp.views' to 'Myapp Views'
        parts = logger_name.split('.')
        return ' '.join(p.replace('_', ' ').title() for p in parts)

    @staticmethod
    def _detect_category(logger_name: str) -> str:
        """Detect category from logger name."""
        if not logger_name:
            return 'root'
        if logger_name.startswith('django'):
            return 'django'
        if logger_name in ('celery', 'uvicorn', 'gunicorn', 'channels', 'redis'):
            return 'infrastructure'
        if logger_name.startswith(('celery.', 'uvicorn.', 'gunicorn.', 'channels.')):
            return 'infrastructure'
        return 'application'


# Singleton instance
settings = QuarkWorkersSettings()

