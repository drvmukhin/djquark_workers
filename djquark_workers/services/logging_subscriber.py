"""
Logging Configuration Subscriber

Redis Pub/Sub subscriber that listens for logging configuration changes
and applies them to the local Python logging system.

This enables real-time synchronization of logging levels across all
worker processes.

Usage:
    from djquark_workers.services import LoggingSubscriber

    # Start subscriber (handled automatically by AppConfig)
    LoggingSubscriber.start()

    # Stop subscriber (on shutdown)
    LoggingSubscriber.stop()
"""

import json
import logging
import threading
import time
from typing import Optional, Any

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


class LoggingSubscriber:
    """
    Redis Pub/Sub subscriber for logging configuration updates.

    Runs as a daemon thread, listening for broadcast messages from
    other workers and applying logging changes to the local Python
    logging system.
    """

    _thread: Optional[threading.Thread] = None
    _running: bool = False
    _pubsub: Any = None
    _restart_count: int = 0
    _max_restarts: int = 5

    @classmethod
    def start(cls) -> None:
        """Start the subscriber thread if not already running."""
        if cls._thread and cls._thread.is_alive():
            return

        cls._running = True
        cls._restart_count = 0
        cls._thread = threading.Thread(
            target=cls._listen_loop,
            daemon=True,
            name="QuarkLoggingSubscriber"
        )
        cls._thread.start()

    @classmethod
    def stop(cls) -> None:
        """Stop the subscriber thread gracefully."""
        cls._running = False

        # Unsubscribe to break the blocking listen
        if cls._pubsub:
            try:
                cls._pubsub.unsubscribe()
                cls._pubsub.close()
            except Exception:
                pass
            cls._pubsub = None

        if cls._thread:
            cls._thread.join(timeout=2.0)
            cls._thread = None

    @classmethod
    def is_running(cls) -> bool:
        """Check if subscriber is running."""
        return cls._running and cls._thread and cls._thread.is_alive()

    @classmethod
    def _listen_loop(cls) -> None:
        """
        Main listener loop (runs in background thread).

        Subscribes to Redis pub/sub channel and processes messages.
        Auto-restarts on failure with exponential backoff.
        """
        from djquark_workers.services.worker_registry import WorkerRegistry

        worker_id = WorkerRegistry.get_worker_id()
        logger.info(f"[{worker_id}] Starting logging config subscriber")

        backoff = 1  # Initial backoff in seconds

        while cls._running:
            try:
                cls._subscribe_and_listen(worker_id)
                backoff = 1  # Reset backoff on clean exit

            except Exception as e:
                if not cls._running:
                    break

                cls._restart_count += 1
                logger.error(
                    f"[{worker_id}] Subscriber error (attempt {cls._restart_count}): {e}"
                )

                if cls._restart_count >= cls._max_restarts:
                    logger.error(
                        f"[{worker_id}] Max restart attempts reached, subscriber stopped"
                    )
                    break

                # Exponential backoff with max of 30 seconds
                time.sleep(min(backoff, 30))
                backoff *= 2

        logger.info(f"[{worker_id}] Logging config subscriber stopped")

    @classmethod
    def _subscribe_and_listen(cls, worker_id: str) -> None:
        """Subscribe to channel and process messages."""
        redis_client = _get_redis_client()
        channel = _get_logging_channel()

        cls._pubsub = redis_client.pubsub()
        cls._pubsub.subscribe(channel)

        logger.debug(f"[{worker_id}] Subscribed to {channel}")

        while cls._running:
            try:
                # get_message with timeout allows periodic check of _running flag
                message = cls._pubsub.get_message(timeout=1.0)

                if message and message['type'] == 'message':
                    cls._handle_message(message, worker_id)

            except Exception as e:
                if cls._running:
                    raise  # Re-raise to trigger restart logic
                break

    @classmethod
    def _handle_message(cls, message: dict, worker_id: str) -> None:
        """
        Process a received pub/sub message.

        Args:
            message: Redis pub/sub message dict
            worker_id: Current worker's ID for logging
        """
        try:
            # Parse message data
            data = message.get('data')
            if isinstance(data, bytes):
                data = data.decode('utf-8')

            if not data or not isinstance(data, str):
                return

            payload = json.loads(data)

            action = payload.get('action')
            sender = payload.get('sender', 'unknown')

            # Skip messages from ourselves
            if sender == worker_id:
                logger.debug(f"[{worker_id}] Ignoring own broadcast")
                return

            # Import here to avoid circular imports
            from djquark_workers.services.logging_manager import LoggingManager

            if action == 'set_level':
                logger_name = payload.get('payload', {}).get('logger_name', '')
                level = payload.get('payload', {}).get('level', 'INFO')

                logger.info(
                    f"[{worker_id}] Received broadcast from {sender}: "
                    f"{logger_name or 'root'} → {level}"
                )

                LoggingManager.set_level(logger_name, level, broadcast=False)

            elif action == 'set_multiple':
                levels = payload.get('payload', {}).get('levels', {})

                logger.info(
                    f"[{worker_id}] Received bulk broadcast from {sender}: "
                    f"{len(levels)} logger(s)"
                )

                LoggingManager.set_multiple_levels(levels, broadcast=False)

            elif action == 'reset':
                logger.info(
                    f"[{worker_id}] Received reset broadcast from {sender}"
                )

                LoggingManager.reset_to_defaults(broadcast=False)

            else:
                logger.warning(f"[{worker_id}] Unknown action: {action}")

        except json.JSONDecodeError as e:
            logger.warning(f"[{worker_id}] Invalid JSON in broadcast: {e}")
        except Exception as e:
            logger.error(f"[{worker_id}] Error handling broadcast: {e}")

