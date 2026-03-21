"""
djquark-workers: Django Multi-Worker Registration and Dynamic Logging Management

A Django app for managing worker registration across distributed processes
(Gunicorn, Uvicorn, Celery, Celery Beat) and dynamic runtime logging configuration.
"""

__version__ = "0.2.0"
__author__ = "Vasily Mukhin <vmukhin.dev@gmail.com>"

# Convenience imports
from djquark_workers.services.worker_registry import WorkerRegistry
from djquark_workers.services.logging_manager import LoggingManager
from djquark_workers.services.logging_subscriber import LoggingSubscriber
from djquark_workers.logging import WorkerIdFilter

__all__ = [
    "WorkerRegistry",
    "LoggingManager",
    "LoggingSubscriber",
    "WorkerIdFilter",
]

default_app_config = "djquark_workers.apps.DjquarkWorkersConfig"

