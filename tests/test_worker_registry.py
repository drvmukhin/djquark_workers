"""
Tests for WorkerRegistry service.
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestWorkerRegistry:
    """Test cases for WorkerRegistry."""

    def test_get_worker_id_returns_default_when_not_registered(self):
        """Worker ID should return 'wk-00' before registration."""
        from djquark_workers.services.worker_registry import WorkerRegistry

        # Reset state
        WorkerRegistry._worker_id = None
        WorkerRegistry._registered = False

        assert WorkerRegistry.get_worker_id() == "wk-00"

    @patch('djquark_workers.services.worker_registry._get_redis_client')
    def test_register_assigns_worker_id(self, mock_redis):
        """Registration should assign a unique worker ID."""
        from djquark_workers.services.worker_registry import WorkerRegistry

        # Reset state
        WorkerRegistry._worker_id = None
        WorkerRegistry._registered = False
        WorkerRegistry._running = False
        WorkerRegistry._heartbeat_thread = None

        # Mock Redis responses
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_client.smembers.return_value = set()
        mock_client.setnx.return_value = True
        mock_client.sadd.return_value = 1

        with patch('djquark_workers.services.worker_registry._detect_process_type') as mock_detect:
            mock_detect.return_value = ('wk', 'web')

            worker_id = WorkerRegistry.register()

            assert worker_id == "wk-01"
            assert WorkerRegistry._registered is True

    def test_detect_process_type_default_to_web(self):
        """Default process type should be web worker."""
        from djquark_workers.services.worker_registry import _detect_process_type

        with patch('sys.argv', ['manage.py', 'runserver']):
            prefix, process_type = _detect_process_type()
            assert prefix == 'wk'
            assert process_type == 'web'

    def test_detect_process_type_celery_worker(self):
        """Should detect Celery worker process."""
        from djquark_workers.services.worker_registry import _detect_process_type

        with patch('sys.argv', ['celery', 'worker', '-A', 'myapp']):
            prefix, process_type = _detect_process_type()
            assert prefix == 'cw'
            assert process_type == 'celery'

    def test_detect_process_type_celery_beat(self):
        """Should detect Celery beat process."""
        from djquark_workers.services.worker_registry import _detect_process_type

        with patch('sys.argv', ['celery', 'beat', '-A', 'myapp']):
            prefix, process_type = _detect_process_type()
            assert prefix == 'bt'
            assert process_type == 'beat'


class TestIsPidAlive:
    """Tests for WorkerRegistry._is_pid_alive."""

    def test_current_process_is_alive(self):
        """Current process PID should be reported as alive."""
        from djquark_workers.services.worker_registry import WorkerRegistry
        assert WorkerRegistry._is_pid_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        """A non-existent PID should be reported as dead."""
        from djquark_workers.services.worker_registry import WorkerRegistry
        # PID 0 is kernel; use a very large PID unlikely to exist
        assert WorkerRegistry._is_pid_alive(99999999) is False

    def test_permission_error_treated_as_alive(self):
        """If os.kill raises PermissionError the process is still alive."""
        from djquark_workers.services.worker_registry import WorkerRegistry
        with patch('os.kill', side_effect=PermissionError):
            assert WorkerRegistry._is_pid_alive(1234) is True

    def test_generic_oserror_treated_as_dead(self):
        """An unexpected OSError should be treated as dead."""
        from djquark_workers.services.worker_registry import WorkerRegistry
        with patch('os.kill', side_effect=OSError):
            assert WorkerRegistry._is_pid_alive(1234) is False


class TestGetWorkerPid:
    """Tests for WorkerRegistry._get_worker_pid."""

    def test_returns_pid_from_redis_hash(self):
        from djquark_workers.services.worker_registry import WorkerRegistry
        mock_client = MagicMock()
        mock_client.hget.return_value = b'42'
        assert WorkerRegistry._get_worker_pid(mock_client, 'some:key') == 42

    def test_returns_none_when_no_pid(self):
        from djquark_workers.services.worker_registry import WorkerRegistry
        mock_client = MagicMock()
        mock_client.hget.return_value = None
        assert WorkerRegistry._get_worker_pid(mock_client, 'some:key') is None

    def test_returns_none_on_invalid_pid(self):
        from djquark_workers.services.worker_registry import WorkerRegistry
        mock_client = MagicMock()
        mock_client.hget.return_value = b'not-a-number'
        assert WorkerRegistry._get_worker_pid(mock_client, 'some:key') is None


class TestCleanupStaleWorkers:
    """Tests for _cleanup_stale_workers (TTL-only, no PID check)."""

    @patch('djquark_workers.services.worker_registry._get_redis_client')
    @patch('djquark_workers.services.worker_registry._get_redis_keys')
    def test_removes_worker_with_expired_heartbeat(self, mock_keys, mock_redis):
        """Workers whose heartbeat key is gone should be cleaned up."""
        from djquark_workers.services.worker_registry import WorkerRegistry

        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_keys.return_value = {
            'WORKERS_SET': 'prefix:set',
            'WORKER_HEARTBEAT': 'prefix:{worker_id}:heartbeat',
            'WORKER_INFO': 'prefix:{worker_id}:info',
        }

        mock_client.smembers.return_value = {b'wk-01'}
        mock_client.exists.return_value = False  # heartbeat expired

        removed = WorkerRegistry._cleanup_stale_workers()
        assert removed == 1
        mock_client.srem.assert_called_once()

    @patch('djquark_workers.services.worker_registry._get_redis_client')
    @patch('djquark_workers.services.worker_registry._get_redis_keys')
    def test_keeps_worker_with_live_heartbeat(self, mock_keys, mock_redis):
        """Workers with a live heartbeat should NOT be removed."""
        from djquark_workers.services.worker_registry import WorkerRegistry

        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_keys.return_value = {
            'WORKERS_SET': 'prefix:set',
            'WORKER_HEARTBEAT': 'prefix:{worker_id}:heartbeat',
            'WORKER_INFO': 'prefix:{worker_id}:info',
        }

        mock_client.smembers.return_value = {b'wk-01'}
        mock_client.exists.return_value = True

        removed = WorkerRegistry._cleanup_stale_workers()
        assert removed == 0
        mock_client.srem.assert_not_called()


class TestWorkerRegistryIntegration:
    """Integration tests requiring Redis connection."""

    @pytest.mark.skipif(True, reason="Requires Redis connection")
    def test_full_registration_cycle(self):
        """Test full registration, heartbeat, and unregistration."""
        from djquark_workers.services.worker_registry import WorkerRegistry

        # Register
        worker_id = WorkerRegistry.register()
        assert worker_id.startswith('wk-')

        # Verify in active workers
        active = WorkerRegistry.get_active_workers()
        assert worker_id in active

        # Unregister
        WorkerRegistry.unregister()

        # Verify removed
        active = WorkerRegistry.get_active_workers()
        assert worker_id not in active

