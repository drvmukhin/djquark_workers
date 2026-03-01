"""
Tests for LoggingManager service.
"""
import logging
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestLoggingManager:
    """Test cases for LoggingManager."""

    def test_get_level_returns_current_level(self):
        """Should return the current log level of a logger."""
        from djquark_workers.services.logging_manager import LoggingManager

        test_logger = logging.getLogger('test.get_level')
        test_logger.setLevel(logging.WARNING)

        level = LoggingManager.get_level('test.get_level')
        assert level == 'WARNING'

    def test_get_effective_level(self):
        """Should return effective level considering parent loggers."""
        from djquark_workers.services.logging_manager import LoggingManager

        parent = logging.getLogger('test.parent')
        parent.setLevel(logging.ERROR)

        child = logging.getLogger('test.parent.child')
        # Child doesn't have explicit level, inherits from parent

        effective = LoggingManager.get_effective_level('test.parent.child')
        assert effective == 'ERROR'

    @patch('djquark_workers.services.logging_manager._get_redis_client')
    @patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id')
    def test_set_level_changes_logger_level(self, mock_worker_id, mock_redis):
        """Setting level should change the actual logger level."""
        from djquark_workers.services.logging_manager import LoggingManager

        mock_worker_id.return_value = 'wk-01'
        mock_redis.return_value = MagicMock()

        test_logger = logging.getLogger('test.set_level')
        test_logger.setLevel(logging.INFO)

        with patch.object(LoggingManager, '_save_to_cache'):
            with patch.object(LoggingManager, '_broadcast_change'):
                success = LoggingManager.set_level('test.set_level', 'DEBUG', broadcast=False)

        assert success is True
        assert test_logger.level == logging.DEBUG

    def test_set_level_invalid_level(self):
        """Should return False for invalid log level."""
        from djquark_workers.services.logging_manager import LoggingManager

        with patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id', return_value='wk-01'):
            success = LoggingManager.set_level('test.invalid', 'INVALID_LEVEL', broadcast=False)

        assert success is False

    @patch('djquark_workers.services.logging_manager._get_redis_client')
    @patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id')
    def test_set_multiple_levels(self, mock_worker_id, mock_redis):
        """Should set multiple logger levels at once."""
        from djquark_workers.services.logging_manager import LoggingManager

        mock_worker_id.return_value = 'wk-01'
        mock_redis.return_value = MagicMock()

        levels = {
            'test.multi.one': 'DEBUG',
            'test.multi.two': 'WARNING',
        }

        with patch.object(LoggingManager, '_save_all_to_cache'):
            with patch.object(LoggingManager, '_broadcast_bulk_change'):
                success = LoggingManager.set_multiple_levels(levels, broadcast=False)

        assert success is True
        assert logging.getLogger('test.multi.one').level == logging.DEBUG
        assert logging.getLogger('test.multi.two').level == logging.WARNING


class TestLoggingManagerBroadcast:
    """Test cases for broadcast functionality."""

    @patch('djquark_workers.services.logging_manager._get_redis_client')
    @patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id')
    def test_broadcast_change_publishes_to_redis(self, mock_worker_id, mock_redis):
        """Broadcast should publish message to Redis pub/sub."""
        from djquark_workers.services.logging_manager import LoggingManager

        mock_worker_id.return_value = 'wk-01'
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_client.publish.return_value = 3  # 3 subscribers

        LoggingManager._broadcast_change('myapp', 'DEBUG')

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert 'logging' in call_args[0][0]  # Channel contains 'logging'

    @patch('djquark_workers.services.logging_manager._get_redis_client')
    @patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id')
    def test_broadcast_reset_publishes_reset_action(self, mock_worker_id, mock_redis):
        """Reset broadcast should publish reset action."""
        from djquark_workers.services.logging_manager import LoggingManager
        import json

        mock_worker_id.return_value = 'wk-01'
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        LoggingManager._broadcast_reset()

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        message = json.loads(call_args[0][1])
        assert message['action'] == 'reset'

