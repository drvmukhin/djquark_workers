"""
Tests for WorkerIdFilter logging filter.
"""
import logging
import pytest
from unittest.mock import patch


class TestWorkerIdFilter:
    """Test cases for WorkerIdFilter."""

    def test_filter_adds_worker_id_attribute(self):
        """Filter should add worker_id to log record."""
        from djquark_workers.logging import WorkerIdFilter

        # Reset cache
        WorkerIdFilter._cached_worker_id = None

        filter_instance = WorkerIdFilter(default_id='test-00')
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )

        with patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id', return_value='wk-01'):
            result = filter_instance.filter(record)

        assert result is True
        assert hasattr(record, 'worker_id')
        assert record.worker_id == 'wk-01'

    def test_filter_uses_default_id_on_error(self):
        """Filter should use default_id when WorkerRegistry fails."""
        from djquark_workers.logging import WorkerIdFilter

        # Reset cache
        WorkerIdFilter._cached_worker_id = None

        filter_instance = WorkerIdFilter(default_id='fallback-00')
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )

        with patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id', side_effect=Exception('Redis error')):
            result = filter_instance.filter(record)

        assert result is True
        assert record.worker_id == 'fallback-00'

    def test_filter_caches_worker_id(self):
        """Filter should cache worker_id after first lookup."""
        from djquark_workers.logging import WorkerIdFilter

        # Set cached value
        WorkerIdFilter._cached_worker_id = 'cached-01'

        filter_instance = WorkerIdFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )

        # Should use cached value without calling WorkerRegistry
        result = filter_instance.filter(record)

        assert result is True
        assert record.worker_id == 'cached-01'

        # Cleanup
        WorkerIdFilter._cached_worker_id = None

    def test_reset_cache(self):
        """reset_cache should clear the cached worker ID."""
        from djquark_workers.logging import WorkerIdFilter

        WorkerIdFilter._cached_worker_id = 'old-id'
        WorkerIdFilter.reset_cache()

        assert WorkerIdFilter._cached_worker_id is None


class TestWorkerIdFilterIntegration:
    """Integration tests for WorkerIdFilter with logging."""

    def test_filter_in_logging_config(self):
        """WorkerIdFilter should work in standard logging configuration."""
        from djquark_workers.logging import WorkerIdFilter

        # Reset cache
        WorkerIdFilter._cached_worker_id = None

        # Create a logger with our filter
        test_logger = logging.getLogger('test.filter.integration')
        test_logger.setLevel(logging.DEBUG)

        # Create handler with formatter that uses worker_id
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('[{worker_id}] {message}', style='{')
        handler.setFormatter(formatter)
        handler.addFilter(WorkerIdFilter(default_id='int-00'))

        test_logger.addHandler(handler)

        # This should not raise an error
        with patch('djquark_workers.services.worker_registry.WorkerRegistry.get_worker_id', return_value='wk-test'):
            test_logger.info('Test log message')

        # Cleanup
        test_logger.removeHandler(handler)
        WorkerIdFilter._cached_worker_id = None

