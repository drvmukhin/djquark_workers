"""
Worker Registry Service

Manages unique worker identification and registration in Redis.
Enables multi-worker coordination and observability.

Usage:
    from djquark_workers.services import WorkerRegistry

    # On startup (handled automatically by AppConfig)
    WorkerRegistry.register()

    # Get current worker ID
    worker_id = WorkerRegistry.get_worker_id()  # "wk-01", "cw-01", or "bt-01"

    # Get all active workers
    workers = WorkerRegistry.get_active_workers()  # ["wk-01", "wk-02", "cw-01"]
"""

import os
import sys
import socket
import threading
import time
import logging
import atexit
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def _get_settings():
    """Get worker registry settings from package config."""
    from djquark_workers.conf import settings
    return {
        'HEARTBEAT_INTERVAL': settings.HEARTBEAT_INTERVAL,
        'HEARTBEAT_TTL': settings.HEARTBEAT_TTL,
        'REDIS_PREFIX': settings.REDIS_PREFIX,
    }


def _get_redis_keys():
    """Get Redis key patterns based on configured prefix."""
    settings = _get_settings()
    prefix = settings.get('REDIS_PREFIX', 'quark:workers')
    return {
        'WORKERS_SET': f'{prefix}:set',
        'WORKER_HEARTBEAT': f'{prefix}:{{worker_id}}:heartbeat',
        'WORKER_INFO': f'{prefix}:{{worker_id}}:info',
    }


def _get_redis_client():
    """
    Get a Redis client for worker registry operations.
    Uses configured Redis URL.
    """
    import redis
    from djquark_workers.conf import settings

    redis_url = settings.REDIS_URL
    return redis.from_url(redis_url)


# Worker type prefixes
WORKER_TYPE_WEB = 'wk'       # Gunicorn/Uvicorn web workers
WORKER_TYPE_CELERY = 'cw'    # Celery task workers
WORKER_TYPE_BEAT = 'bt'      # Celery beat scheduler
WORKER_TYPE_BOT = 'bot'      # Discord bot


def _detect_process_type() -> Tuple[str, str]:
    """
    Detect the type of process we're running in.

    Returns:
        Tuple of (prefix, description):
        - ('wk', 'web') for Gunicorn/Uvicorn web workers
        - ('cw', 'celery') for Celery task workers
        - ('bt', 'beat') for Celery beat scheduler
        - ('bot', 'discord_bot') for Discord bot
    """
    # Check command line arguments
    argv_str = ' '.join(sys.argv).lower()

    # Check for Discord bot
    if 'run_role_bot' in argv_str or 'discord_bot' in argv_str or 'run_lfg_bot' in argv_str:
        return (WORKER_TYPE_BOT, 'discord_bot')

    # Check for Celery beat
    if 'celery' in argv_str and 'beat' in argv_str:
        return (WORKER_TYPE_BEAT, 'beat')

    # Check for Celery worker
    if 'celery' in argv_str and ('worker' in argv_str or '-a' in argv_str):
        return (WORKER_TYPE_CELERY, 'celery')

    # Check sys.argv[0] for celery
    if 'celery' in sys.argv[0].lower():
        if len(sys.argv) > 1:
            if sys.argv[1] == 'beat':
                return (WORKER_TYPE_BEAT, 'beat')
            elif sys.argv[1] == 'worker':
                return (WORKER_TYPE_CELERY, 'celery')
        return (WORKER_TYPE_CELERY, 'celery')

    # Default to web worker (Gunicorn/Uvicorn)
    return (WORKER_TYPE_WEB, 'web')


class WorkerRegistry:
    """
    Manages worker registration in Redis.

    Each Gunicorn/Uvicorn worker registers with a unique ID (wk-01, wk-02, etc.)
    and maintains a heartbeat. This enables:
    - Worker identification in logs
    - Multi-worker coordination
    - Detection of dead workers
    """

    _worker_id: Optional[str] = None
    _heartbeat_thread: Optional[threading.Thread] = None
    _running: bool = False
    _registered: bool = False
    _process_type: str = 'unknown'

    @classmethod
    def register(cls) -> str:
        """
        Register this worker instance in Redis.

        Returns:
            The assigned worker ID (e.g., "wk-01")
        """
        if cls._registered and cls._worker_id:
            return cls._worker_id

        try:
            # Clean up workers whose heartbeat TTL has expired so their
            # slots become available for reuse by _assign_worker_id().
            cls._cleanup_stale_workers()

            # Assign worker ID
            cls._worker_id = cls._assign_worker_id()

            # Store worker info
            cls._store_worker_info()

            # Start heartbeat thread
            cls._start_heartbeat()

            # Register atexit handler for cleanup
            atexit.register(cls.unregister)

            cls._registered = True

            # Reset the WorkerIdFilter cache
            try:
                from djquark_workers.logging import WorkerIdFilter
                WorkerIdFilter.reset_cache()
            except Exception:
                pass

            logger.info(f"[{cls._worker_id}] Worker registered successfully")

            return cls._worker_id

        except Exception as e:
            logger.warning(f"Could not register worker in Redis: {e}")
            # Use fallback ID
            prefix, _ = _detect_process_type()
            cls._worker_id = f"{prefix}-{os.getpid()}"
            return cls._worker_id

    @classmethod
    def unregister(cls) -> None:
        """
        Unregister this worker from Redis.
        Called automatically on shutdown via atexit.
        """
        if not cls._registered or not cls._worker_id:
            return

        try:
            # Stop heartbeat thread
            cls._stop_heartbeat()

            redis_client = _get_redis_client()
            keys = _get_redis_keys()

            worker_id = cls._worker_id

            # Remove from workers set
            redis_client.srem(keys['WORKERS_SET'], worker_id)

            # Delete heartbeat and info keys
            heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=worker_id)
            info_key = keys['WORKER_INFO'].format(worker_id=worker_id)
            redis_client.delete(heartbeat_key, info_key)

            logger.info(f"[{worker_id}] Worker unregistered")

        except Exception as e:
            logger.warning(f"Error unregistering worker: {e}")
        finally:
            cls._registered = False

    @classmethod
    def get_worker_id(cls) -> str:
        """
        Get the current worker's ID.

        Returns:
            Worker ID (e.g., "wk-01") or "wk-00" if not registered
        """
        return cls._worker_id or "wk-00"

    @classmethod
    def get_active_workers(cls) -> List[str]:
        """
        Get list of all active worker IDs.

        Returns:
            Sorted list of worker IDs (e.g., ['bt-01', 'cw-01', 'cw-02', 'wk-01', 'wk-02'])
        """
        try:
            redis_client = _get_redis_client()
            keys = _get_redis_keys()

            workers = redis_client.smembers(keys['WORKERS_SET'])
            worker_list = [
                w.decode() if isinstance(w, bytes) else w
                for w in workers
            ]
            return sorted(worker_list)

        except Exception as e:
            logger.warning(f"Error getting active workers: {e}")
            return [cls.get_worker_id()] if cls._worker_id else []

    @classmethod
    def get_workers_by_type(cls, worker_type: str = None) -> Dict[str, List[str]]:
        """
        Get active workers grouped by type.

        Args:
            worker_type: Optional filter ('web', 'celery', 'beat', 'discord_bot').

        Returns:
            Dict with keys 'web', 'celery', 'beat', 'discord_bot' mapping to lists of worker IDs
        """
        workers = cls.get_active_workers()

        result = {
            'web': [],
            'celery': [],
            'beat': [],
            'discord_bot': [],
        }

        for w in workers:
            if w.startswith('wk-'):
                result['web'].append(w)
            elif w.startswith('cw-'):
                result['celery'].append(w)
            elif w.startswith('bt-'):
                result['beat'].append(w)
            elif w.startswith('bot-'):
                result['discord_bot'].append(w)

        if worker_type:
            return {worker_type: result.get(worker_type, [])}
        return result

    @classmethod
    def get_worker_count(cls) -> int:
        """Get count of active workers."""
        try:
            redis_client = _get_redis_client()
            keys = _get_redis_keys()
            return redis_client.scard(keys['WORKERS_SET']) or 0
        except Exception:
            return 1

    @classmethod
    def get_process_type(cls) -> str:
        """Get the process type of the current worker ('web', 'celery', or 'beat')."""
        return cls._process_type

    @classmethod
    def get_worker_info(cls, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get info for a specific worker."""
        try:
            redis_client = _get_redis_client()
            keys = _get_redis_keys()

            info_key = keys['WORKER_INFO'].format(worker_id=worker_id)
            info = redis_client.hgetall(info_key)

            if info:
                return {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in info.items()
                }
            return None

        except Exception as e:
            logger.warning(f"Error getting worker info: {e}")
            return None

    @classmethod
    def _assign_worker_id(cls) -> str:
        """
        Assign the lowest available worker number based on process type.

        Worker ID format:
        - wk-01, wk-02, ... for web workers (Gunicorn/Uvicorn)
        - cw-01, cw-02, ... for Celery task workers
        - bt-01 for Celery beat scheduler
        - bot-01, ... for Discord bots

        Uses atomic SETNX to handle race conditions between workers.
        """
        redis_client = _get_redis_client()
        keys = _get_redis_keys()
        settings = _get_settings()
        heartbeat_ttl = settings.get('HEARTBEAT_TTL', 60)

        # Detect process type
        prefix, process_type = _detect_process_type()
        cls._process_type = process_type

        for attempt in range(10):
            # Get existing workers
            existing = redis_client.smembers(keys['WORKERS_SET'])
            existing_nums = set()

            for w in existing:
                w_str = w.decode() if isinstance(w, bytes) else w
                if w_str.startswith(f'{prefix}-'):
                    try:
                        num = int(w_str.split('-')[1])
                        existing_nums.add(num)
                    except (ValueError, IndexError):
                        pass

            # Find lowest available number
            for num in range(1, 100):
                if num not in existing_nums:
                    candidate = f"{prefix}-{num:02d}"

                    # Try to claim atomically using SETNX
                    heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=candidate)
                    timestamp = datetime.now(timezone.utc).isoformat()

                    if redis_client.setnx(heartbeat_key, timestamp):
                        redis_client.expire(heartbeat_key, heartbeat_ttl)
                        redis_client.sadd(keys['WORKERS_SET'], candidate)
                        return candidate

            # All numbers taken or race condition, retry
            time.sleep(0.1)

        # Fallback: use PID-based ID
        return f"{prefix}-{os.getpid()}"

    @classmethod
    def _store_worker_info(cls) -> None:
        """Store metadata about this worker."""
        try:
            redis_client = _get_redis_client()
            keys = _get_redis_keys()
            settings = _get_settings()
            heartbeat_ttl = settings.get('HEARTBEAT_TTL', 60)

            info_key = keys['WORKER_INFO'].format(worker_id=cls._worker_id)
            info = {
                'pid': str(os.getpid()),
                'hostname': socket.gethostname(),
                'started_at': datetime.now(timezone.utc).isoformat(),
                'process_type': cls._process_type,
            }

            redis_client.hset(info_key, mapping=info)
            redis_client.expire(info_key, heartbeat_ttl)

        except Exception as e:
            logger.warning(f"Could not store worker info: {e}")

    @classmethod
    def _start_heartbeat(cls) -> None:
        """Start the background heartbeat thread."""
        if cls._heartbeat_thread and cls._heartbeat_thread.is_alive():
            return

        cls._running = True
        cls._heartbeat_thread = threading.Thread(
            target=cls._heartbeat_loop,
            daemon=True,
            name=f"WorkerHeartbeat-{cls._worker_id}"
        )
        cls._heartbeat_thread.start()

    @classmethod
    def _stop_heartbeat(cls) -> None:
        """Stop the heartbeat thread gracefully."""
        cls._running = False
        if cls._heartbeat_thread:
            cls._heartbeat_thread.join(timeout=2.0)
            cls._heartbeat_thread = None

    @classmethod
    def _heartbeat_loop(cls) -> None:
        """Background loop that sends heartbeats to Redis."""
        settings = _get_settings()
        interval = settings.get('HEARTBEAT_INTERVAL', 30)
        ttl = settings.get('HEARTBEAT_TTL', 60)
        keys = _get_redis_keys()

        worker_id = cls._worker_id
        heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=worker_id)
        info_key = keys['WORKER_INFO'].format(worker_id=worker_id)

        while cls._running:
            try:
                redis_client = _get_redis_client()
                timestamp = datetime.now(timezone.utc).isoformat()

                # Update heartbeat with TTL
                redis_client.set(heartbeat_key, timestamp, ex=ttl)

                # Refresh info TTL
                redis_client.expire(info_key, ttl)

            except Exception as e:
                logger.warning(f"[{worker_id}] Heartbeat failed: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(int(interval)):
                if not cls._running:
                    break
                time.sleep(1)

    @classmethod
    def _cleanup_stale_workers(cls) -> int:
        """
        Remove workers whose heartbeat keys have expired.

        This is the TTL-based cleanup only. For PID-liveness-aware cleanup
        (e.g. catching OOM-killed workers whose TTL hasn't expired), use
        the ``cleanup_workers`` management command.

        Returns:
            Number of stale workers removed
        """
        try:
            redis_client = _get_redis_client()
            keys = _get_redis_keys()

            # Get all registered workers
            workers = redis_client.smembers(keys['WORKERS_SET'])
            removed = 0

            for worker in workers:
                worker_id = worker.decode() if isinstance(worker, bytes) else worker
                heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=worker_id)

                # If heartbeat key doesn't exist, worker is dead
                if not redis_client.exists(heartbeat_key):
                    redis_client.srem(keys['WORKERS_SET'], worker_id)
                    info_key = keys['WORKER_INFO'].format(worker_id=worker_id)
                    redis_client.delete(info_key)
                    removed += 1
                    logger.debug(f"Cleaned up stale worker: {worker_id}")

            if removed > 0:
                logger.info(f"Cleaned up {removed} stale worker(s)")

            return removed

        except Exception as e:
            logger.warning(f"Error cleaning up stale workers: {e}")
            return 0

    @staticmethod
    def _get_worker_pid(redis_client, info_key: str) -> Optional[int]:
        """
        Get the PID stored for a worker from its Redis info hash.

        Returns:
            The PID as int, or None if not available.
        """
        try:
            pid_str = redis_client.hget(info_key, 'pid')
            if pid_str:
                return int(pid_str.decode() if isinstance(pid_str, bytes) else pid_str)
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """
        Check if a process with the given PID is still running.

        Uses os.kill(pid, 0) which checks existence without sending a signal.

        Note: This check is only meaningful on the same host. In multi-host
        deployments the PID may belong to an unrelated process.
        """
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            # errno.ESRCH — No such process
            return False
        except PermissionError:
            # errno.EPERM — Process exists but we can't signal it
            # (different user). Consider it alive.
            return True
        except OSError:
            return False

