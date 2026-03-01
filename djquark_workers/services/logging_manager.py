"""
Dynamic Logging Configuration Manager

Provides runtime logging level configuration without server restart.
Uses Redis pub/sub to propagate changes across all worker processes.

Usage:
    from djquark_workers.services import LoggingManager

    # Change logging level for a module
    LoggingManager.set_level('myapp', 'DEBUG')

    # Get current levels
    levels = LoggingManager.get_all_levels()

    # Apply saved configuration (called on worker startup)
    LoggingManager.apply_saved_config()
"""

import logging
import logging.config
import json
from datetime import datetime, timezone
from typing import Dict, Optional, List
from django.core.cache import cache
from django.conf import settings as django_settings

logger = logging.getLogger(__name__)


def _get_redis_client():
    """Get a Redis client for pub/sub operations."""
    import redis
    from djquark_workers.conf import settings
    return redis.from_url(settings.REDIS_URL)


def _get_logging_channel():
    """Get the Redis pub/sub channel name for logging updates."""
    from djquark_workers.conf import settings
    return f"{settings.LOGGING_PREFIX}:updates"


def _get_cache_key():
    """Get the cache key for storing logging configuration."""
    from djquark_workers.conf import settings
    return f"{settings.LOGGING_PREFIX}:config"


def get_default_level_from_settings(logger_name: str) -> str:
    """
    Get the default log level for a logger from settings.py LOGGING config.

    Args:
        logger_name: The logger name

    Returns:
        The default level from settings, or 'INFO' if not found
    """
    try:
        logging_config = getattr(django_settings, 'LOGGING', {})
        loggers = logging_config.get('loggers', {})

        if logger_name in loggers:
            return loggers[logger_name].get('level', 'INFO')

        # For root logger
        if logger_name == '' and '' in loggers:
            return loggers[''].get('level', 'INFO')

        # Fall back to LOG_LEVEL setting
        return getattr(django_settings, 'LOG_LEVEL', 'INFO')
    except Exception:
        return 'INFO'


class LoggingManager:
    """
    Manages dynamic logging configuration across worker processes.

    Architecture:
    1. Configuration is stored in database (persistent) and Redis cache (fast access)
    2. When config changes, broadcasts via Redis pub/sub to all workers
    3. Each worker applies changes immediately to Python's logging module
    4. On worker startup, applies saved configuration from database
    """

    @classmethod
    def get_level(cls, logger_name: str) -> str:
        """Get the current log level for a logger."""
        log = logging.getLogger(logger_name)
        level = log.level
        if level == 0:  # NOTSET
            return 'NOTSET'
        return logging.getLevelName(level)

    @classmethod
    def get_effective_level(cls, logger_name: str) -> str:
        """Get the effective log level (considering parent loggers)."""
        log = logging.getLogger(logger_name)
        return logging.getLevelName(log.getEffectiveLevel())

    @classmethod
    def get_all_levels(cls) -> Dict[str, Dict]:
        """
        Get current levels for all configurable loggers.

        Returns:
            Dict mapping logger names to their info:
            {
                'myapp': {
                    'display_name': 'My Application',
                    'category': 'application',
                    'current_level': 'INFO',
                    'effective_level': 'INFO',
                    'default_level': 'INFO',
                },
                ...
            }
        """
        from djquark_workers.conf import settings

        result = {}
        for name, display_name, category in settings.CONFIGURABLE_LOGGERS:
            result[name] = {
                'display_name': display_name,
                'category': category,
                'current_level': cls.get_level(name),
                'effective_level': cls.get_effective_level(name),
                'default_level': get_default_level_from_settings(name),
            }
        return result

    @classmethod
    def set_level(cls, logger_name: str, level: str, broadcast: bool = True) -> bool:
        """
        Set the log level for a logger in the current process.

        Args:
            logger_name: The logger name (e.g., 'myapp', 'uvicorn.access')
            level: The log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            broadcast: Whether to broadcast change to other workers

        Returns:
            True if successful, False otherwise
        """
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry
            worker_id = WorkerRegistry.get_worker_id()

            # Validate level
            level_upper = level.upper()
            numeric_level = getattr(logging, level_upper, None)
            if numeric_level is None:
                logger.error(f"[{worker_id}] Invalid log level: {level}")
                return False

            # Apply to logger
            target_logger = logging.getLogger(logger_name)
            target_logger.setLevel(numeric_level)

            logger.info(f"[{worker_id}] Set logger '{logger_name or 'root'}' to level {level_upper}")

            # Save to cache and broadcast if requested
            if broadcast:
                cls._save_to_cache(logger_name, level_upper)
                cls._broadcast_change(logger_name, level_upper)

            return True

        except Exception as e:
            logger.exception(f"Error setting log level: {e}")
            return False

    @classmethod
    def set_multiple_levels(cls, levels: Dict[str, str], broadcast: bool = True) -> bool:
        """
        Set multiple logger levels at once.

        Args:
            levels: Dict mapping logger names to levels
            broadcast: Whether to broadcast changes

        Returns:
            True if all successful
        """
        success = True
        for logger_name, level in levels.items():
            if not cls.set_level(logger_name, level, broadcast=False):
                success = False

        if broadcast:
            cls._save_all_to_cache(levels)
            cls._broadcast_bulk_change(levels)

        return success

    @classmethod
    def apply_saved_config(cls) -> int:
        """
        Apply saved logging configuration from database.
        Falls back to Redis cache if database is not available.
        Called on worker startup to restore dynamic settings.

        Returns:
            Number of configurations applied
        """
        from djquark_workers.services.worker_registry import WorkerRegistry
        worker_id = WorkerRegistry.get_worker_id()

        configs = {}

        # First try: Load from Redis cache (faster, works even if DB isn't ready)
        try:
            cached_config = cls._load_from_cache()
            if cached_config:
                configs = cached_config
                logger.debug(f"[{worker_id}] Loaded {len(configs)} logging config(s) from Redis cache")
        except Exception as e:
            logger.debug(f"[{worker_id}] Could not load logging config from cache: {e}")

        # Second try: Load from database (authoritative source)
        try:
            from djquark_workers.models import LoggingConfig
            db_configs = LoggingConfig.get_all_active()
            if db_configs:
                configs = db_configs
                cls._save_all_to_cache(configs)
                logger.debug(f"[{worker_id}] Loaded {len(configs)} logging config(s) from database")
        except Exception as e:
            logger.warning(f"[{worker_id}] Could not load logging config from database: {e}")

        if not configs:
            logger.debug(f"[{worker_id}] No custom logging configurations to apply")
            return 0

        # Apply configurations
        count = 0
        for logger_name, level in configs.items():
            if cls.set_level(logger_name, level, broadcast=False):
                count += 1

        if count > 0:
            logger.info(f"[{worker_id}] Applied {count} saved logging config(s) on startup")

        return count

    @classmethod
    def reset_to_defaults(cls, broadcast: bool = True) -> None:
        """Reset all loggers to their default levels from settings.py."""
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry
            worker_id = WorkerRegistry.get_worker_id()

            # Clear cache
            cache_key = _get_cache_key()
            cache.delete(cache_key)

            # Re-apply from Django settings
            if hasattr(django_settings, 'LOGGING'):
                logging.config.dictConfig(django_settings.LOGGING)

            logger.info(f"[{worker_id}] Reset logging configuration to defaults")

            # Broadcast reset to all workers
            if broadcast:
                cls._broadcast_reset()

        except Exception as e:
            logger.exception(f"Error resetting logging config: {e}")

    # ==================== Cache Methods ====================

    @classmethod
    def _save_to_cache(cls, logger_name: str, level: str) -> None:
        """Save a single logger's level to Redis cache."""
        try:
            cache_key = _get_cache_key()
            config = cls._load_from_cache() or {}
            config[logger_name] = level
            cache.set(cache_key, json.dumps(config), timeout=None)
        except Exception as e:
            logger.warning(f"Could not save logging config to cache: {e}")

    @classmethod
    def _save_all_to_cache(cls, levels: Dict[str, str]) -> None:
        """Save all logger levels to Redis cache."""
        try:
            cache_key = _get_cache_key()
            config = cls._load_from_cache() or {}
            config.update(levels)
            cache.set(cache_key, json.dumps(config), timeout=None)
        except Exception as e:
            logger.warning(f"Could not save logging config to cache: {e}")

    @classmethod
    def _load_from_cache(cls) -> Optional[Dict[str, str]]:
        """Load logging configuration from Redis cache."""
        try:
            cache_key = _get_cache_key()
            data = cache.get(cache_key)
            if data:
                return json.loads(data) if isinstance(data, str) else data
        except Exception as e:
            logger.warning(f"Error loading logging config from cache: {e}")
        return None

    # ==================== Broadcast Methods ====================

    @classmethod
    def _broadcast_change(cls, logger_name: str, level: str) -> None:
        """Broadcast a logging change to all workers via Redis pub/sub."""
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry

            worker_id = WorkerRegistry.get_worker_id()
            channel = _get_logging_channel()

            message = json.dumps({
                'action': 'set_level',
                'sender': worker_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'payload': {
                    'logger_name': logger_name,
                    'level': level,
                }
            })

            redis_client = _get_redis_client()
            receivers = redis_client.publish(channel, message)

            logger.info(
                f"[{worker_id}] Broadcast logging change: "
                f"{logger_name or 'root'} → {level} ({receivers} subscriber(s))"
            )

        except Exception as e:
            logger.warning(f"Could not broadcast logging change: {e}")

    @classmethod
    def _broadcast_bulk_change(cls, levels: Dict[str, str]) -> None:
        """Broadcast multiple logging changes via Redis pub/sub."""
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry

            worker_id = WorkerRegistry.get_worker_id()
            channel = _get_logging_channel()

            message = json.dumps({
                'action': 'set_multiple',
                'sender': worker_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'payload': {
                    'levels': levels,
                }
            })

            redis_client = _get_redis_client()
            receivers = redis_client.publish(channel, message)

            logger.info(
                f"[{worker_id}] Broadcast bulk logging change: "
                f"{len(levels)} logger(s) ({receivers} subscriber(s))"
            )

        except Exception as e:
            logger.warning(f"Could not broadcast bulk logging change: {e}")

    @classmethod
    def _broadcast_reset(cls) -> None:
        """Broadcast reset command to all workers via Redis pub/sub."""
        try:
            from djquark_workers.services.worker_registry import WorkerRegistry

            worker_id = WorkerRegistry.get_worker_id()
            channel = _get_logging_channel()

            message = json.dumps({
                'action': 'reset',
                'sender': worker_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'payload': {}
            })

            redis_client = _get_redis_client()
            receivers = redis_client.publish(channel, message)

            logger.info(
                f"[{worker_id}] Broadcast logging reset ({receivers} subscriber(s))"
            )

        except Exception as e:
            logger.warning(f"Could not broadcast logging reset: {e}")

    @classmethod
    def handle_broadcast_message(cls, message: dict) -> None:
        """
        Handle a logging config update message from Redis broadcast.
        Called by channel consumer when receiving broadcasts.
        """
        action = message.get('action')

        if action == 'set_level':
            logger_name = message.get('logger_name', '')
            level = message.get('level', 'INFO')
            cls.set_level(logger_name, level, broadcast=False)

        elif action == 'set_multiple':
            levels = message.get('levels', {})
            cls.set_multiple_levels(levels, broadcast=False)

        elif action == 'reset':
            # Re-apply from settings
            if hasattr(django_settings, 'LOGGING'):
                logging.config.dictConfig(django_settings.LOGGING)

