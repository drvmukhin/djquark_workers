"""
Tests for conf module settings.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestQuarkWorkersSettings:
    """Test cases for settings configuration."""

    def test_default_values(self):
        """Settings should have sensible defaults."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()
        settings._cached_settings = None

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_CONFIG = {}
            mock_django_settings.QUARK_WORKERS_REDIS_URL = None
            mock_django_settings.QUARK_WORKERS_REDIS_CACHE = None
            mock_django_settings.REDIS_URL = None
            mock_django_settings.QUARK_WORKERS_LOGGERS = None

            # Check defaults
            assert settings.DEFAULTS['ENABLED'] is True
            assert settings.DEFAULTS['HEARTBEAT_INTERVAL'] == 30
            assert settings.DEFAULTS['HEARTBEAT_TTL'] == 60
            assert settings.DEFAULTS['ADMIN_PERMISSION'] == 'superuser'

    def test_redis_url_from_direct_setting(self):
        """Should use direct QUARK_WORKERS_REDIS_URL if set."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_REDIS_URL = 'redis://myhost:6380/5'
            mock_django_settings.QUARK_WORKERS_REDIS_CACHE = None

            assert settings.REDIS_URL == 'redis://myhost:6380/5'

    def test_redis_url_from_cache_backend(self):
        """Should extract Redis URL from cache backend if configured."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_REDIS_URL = None
            mock_django_settings.QUARK_WORKERS_REDIS_CACHE = 'default'
            mock_django_settings.CACHES = {
                'default': {
                    'BACKEND': 'django_redis.cache.RedisCache',
                    'LOCATION': 'redis://cachehost:6379/1'
                }
            }
            mock_django_settings.REDIS_URL = None

            assert settings.REDIS_URL == 'redis://cachehost:6379/1'

    def test_redis_url_fallback_to_redis_url(self):
        """Should fallback to REDIS_URL setting."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_REDIS_URL = None
            mock_django_settings.QUARK_WORKERS_REDIS_CACHE = None
            mock_django_settings.REDIS_URL = 'redis://fallback:6379/0'

            assert settings.REDIS_URL == 'redis://fallback:6379/0'

    def test_configurable_loggers_from_tuples(self):
        """Should parse logger configuration from tuple format."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_LOGGERS = [
                ('myapp', 'My App', 'application'),
                ('myapp.views', 'Views'),  # 2-tuple
                ('myapp.models',),  # 1-tuple
            ]

            loggers = settings.CONFIGURABLE_LOGGERS

            assert loggers[0] == ('myapp', 'My App', 'application')
            assert loggers[1] == ('myapp.views', 'Views', 'application')
            assert loggers[2][0] == 'myapp.models'

    def test_configurable_loggers_from_strings(self):
        """Should parse logger configuration from string format."""
        from djquark_workers.conf import QuarkWorkersSettings

        settings = QuarkWorkersSettings()

        with patch('django.conf.settings') as mock_django_settings:
            mock_django_settings.QUARK_WORKERS_LOGGERS = [
                '',
                'django',
                'myapp',
                'celery',
            ]

            loggers = settings.CONFIGURABLE_LOGGERS

            # Root logger
            assert loggers[0][0] == ''
            assert loggers[0][1] == 'Root Logger'
            assert loggers[0][2] == 'root'

            # Django logger
            assert loggers[1][0] == 'django'
            assert loggers[1][2] == 'django'

            # App logger
            assert loggers[2][0] == 'myapp'
            assert loggers[2][2] == 'application'

            # Infrastructure logger
            assert loggers[3][0] == 'celery'
            assert loggers[3][2] == 'infrastructure'

    def test_make_display_name(self):
        """Should generate display names from logger names."""
        from djquark_workers.conf import QuarkWorkersSettings

        assert QuarkWorkersSettings._make_display_name('') == 'Root Logger'
        assert QuarkWorkersSettings._make_display_name('myapp') == 'Myapp'
        assert QuarkWorkersSettings._make_display_name('myapp.views') == 'Myapp Views'
        assert QuarkWorkersSettings._make_display_name('my_app.some_module') == 'My App Some Module'

    def test_detect_category(self):
        """Should detect category from logger name."""
        from djquark_workers.conf import QuarkWorkersSettings

        assert QuarkWorkersSettings._detect_category('') == 'root'
        assert QuarkWorkersSettings._detect_category('django') == 'django'
        assert QuarkWorkersSettings._detect_category('django.request') == 'django'
        assert QuarkWorkersSettings._detect_category('celery') == 'infrastructure'
        assert QuarkWorkersSettings._detect_category('uvicorn.access') == 'infrastructure'
        assert QuarkWorkersSettings._detect_category('myapp') == 'application'
        assert QuarkWorkersSettings._detect_category('myapp.views') == 'application'

