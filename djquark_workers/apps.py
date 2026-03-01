"""
Django AppConfig for djquark-workers.

Handles automatic worker registration and logging configuration on startup.
"""

import sys
import os
import atexit
import logging

logger = logging.getLogger(__name__)


class DjquarkWorkersConfig:
    """Django app configuration for djquark-workers."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'djquark_workers'
    verbose_name = 'Quark Workers'

    def __init__(self, app_name, app_module):
        from django.apps import AppConfig
        # We need to properly inherit from AppConfig
        pass


# Proper implementation using Django's AppConfig
from django.apps import AppConfig


class DjquarkWorkersConfig(AppConfig):
    """Django app configuration for djquark-workers."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'djquark_workers'
    verbose_name = 'Quark Workers'

    def ready(self):
        """
        Called when Django starts up.

        In production (Gunicorn/Uvicorn):
        - Register this worker instance
        - Start logging config subscriber
        - Apply saved logging configuration
        """
        from djquark_workers.conf import settings as quark_settings

        # Check if enabled
        if not quark_settings.ENABLED:
            return

        # Skip for management commands that don't need worker registration
        if self._is_skip_command():
            return

        # Register worker in these scenarios:
        #
        # 1. Production (Gunicorn/Uvicorn): _is_dev_server() is False → register
        #
        # 2. Dev server WITH auto-reload (default):
        #    - Django's auto-reloader runs ready() twice
        #    - Parent process: RUN_MAIN not set → skip
        #    - Child process: RUN_MAIN='true' → register
        #
        # 3. Dev server with --noreload flag:
        #    - RUN_MAIN not set, but we still want to register
        #    - Detected by checking for '--noreload' in argv
        #
        is_dev = self._is_dev_server()
        is_reloader_child = os.environ.get('RUN_MAIN') == 'true'
        is_noreload = '--noreload' in sys.argv

        # Register if: production, OR dev reloader child, OR dev with --noreload
        if not is_dev or is_reloader_child or is_noreload:
            self._initialize_worker()

    def _initialize_worker(self):
        """Initialize worker registration, subscriber, and logging config.

        All work is deferred to a background thread so that no database
        queries run inside ready() — Django warns about this since 4.2+.
        Worker registration (Redis-only) and pub/sub startup happen
        immediately on the thread; the DB-backed logging config load
        follows after a short delay to let the connection pool settle.
        """
        import threading

        def background_init():
            """
            Run in a daemon thread so ready() returns immediately.

            Phase 1 (no DB): register worker in Redis, start subscriber.
            Phase 2 (DB): apply saved logging configuration from database.
            """
            import time

            try:
                from djquark_workers.services.worker_registry import WorkerRegistry
                from djquark_workers.services.logging_subscriber import LoggingSubscriber
                from djquark_workers.services.logging_manager import LoggingManager

                # Phase 1: Redis-only, no DB access
                worker_id = WorkerRegistry.register()
                LoggingSubscriber.start()

                # Phase 2: tiny delay, then load config from DB
                # (avoids the "database accessed during app init" warning)
                time.sleep(1.0)
                count = LoggingManager.apply_saved_config()

                logger.info(
                    f"[{worker_id}] djquark-workers initialized. "
                    f"Applied {count} logging config(s)."
                )

            except Exception as e:
                logger.warning(f"Failed to initialize worker: {e}")

        thread = threading.Thread(target=background_init, daemon=True, name="quark-workers-init")
        thread.start()
        atexit.register(self._shutdown)

    @staticmethod
    def _is_skip_command() -> bool:
        """Check if running as a management command that doesn't need worker registration."""
        skip_commands = [
            'migrate', 'makemigrations', 'shell', 'dbshell',
            'collectstatic', 'createsuperuser', 'check', 'test',
            'showmigrations', 'sqlmigrate', 'inspectdb', 'diffsettings',
            'dumpdata', 'loaddata', 'flush', 'startapp', 'startproject',
            'cleanup_workers',  # Don't register worker when cleaning up workers
        ]
        return len(sys.argv) > 1 and sys.argv[1] in skip_commands

    @staticmethod
    def _is_dev_server() -> bool:
        """Check if running Django's development server."""
        return 'runserver' in sys.argv

    @staticmethod
    def _shutdown():
        """Cleanup on worker shutdown."""
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry
            from djquark_workers.services.logging_subscriber import LoggingSubscriber

            worker_id = WorkerRegistry.get_worker_id()

            LoggingSubscriber.stop()
            WorkerRegistry.unregister()

            logger.info(f"[{worker_id}] djquark-workers shutdown complete")

        except Exception as e:
            logger.warning(f"Error during shutdown: {e}")



