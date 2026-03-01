"""
Tests for WorkerRegistry service.
"""
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

