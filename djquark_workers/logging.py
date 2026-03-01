"""
Logging utilities for djquark-workers.

Provides the WorkerIdFilter for including worker ID in log messages.
"""

import logging
from typing import Optional


class WorkerIdFilter(logging.Filter):
    """
    Logging filter that adds worker_id to log records.

    Usage in settings.py:

        LOGGING = {
            'version': 1,
            'filters': {
                'worker_id': {
                    '()': 'djquark_workers.logging.WorkerIdFilter',
                },
            },
            'formatters': {
                'verbose': {
                    'format': '[{worker_id}] {asctime} {levelname} {name}: {message}',
                    'style': '{',
                },
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'verbose',
                    'filters': ['worker_id'],
                },
            },
            ...
        }

    Output:
        [wk-01] 2024-02-28 10:30:00 INFO myapp.views: User logged in
        [cw-02] 2024-02-28 10:30:01 INFO myapp.tasks: Task completed
    """

    _cached_worker_id: Optional[str] = None

    def __init__(self, name: str = '', default_id: str = 'wk-00'):
        """
        Initialize the filter.

        Args:
            name: Standard logging filter name
            default_id: Worker ID to use before registration completes
        """
        super().__init__(name)
        self.default_id = default_id

    def filter(self, record: logging.LogRecord) -> bool:
        """Add worker_id attribute to the log record."""
        # Use cached value if available (avoid repeated imports/lookups)
        if WorkerIdFilter._cached_worker_id is None:
            try:
                from djquark_workers.services.worker_registry import WorkerRegistry
                worker_id = WorkerRegistry.get_worker_id()
                if worker_id and worker_id != 'wk-00':
                    WorkerIdFilter._cached_worker_id = worker_id
                else:
                    worker_id = self.default_id
            except Exception:
                worker_id = self.default_id
        else:
            worker_id = WorkerIdFilter._cached_worker_id

        record.worker_id = worker_id
        return True

    @classmethod
    def reset_cache(cls):
        """Reset the cached worker ID. Called on worker re-registration."""
        cls._cached_worker_id = None

