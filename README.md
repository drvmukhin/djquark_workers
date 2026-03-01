# djquark-workers

A Django app for multi-worker registration and dynamic logging level management across distributed processes (Gunicorn, Uvicorn, Celery, Celery Beat).

## Features

- **Worker Registration**: Automatically registers each worker process (web workers, Celery workers, beat scheduler) with a unique ID in Redis
- **Worker Heartbeat**: Maintains heartbeat to track active workers and detect stale processes
- **Dynamic Logging Management**: Change log levels at runtime without server restart
- **Cross-Worker Sync**: Log level changes propagate to all workers via Redis pub/sub
- **Admin Panel**: Web-based UI for managing logging levels
- **Worker ID in Logs**: Include `{worker_id}` in your log format for easy tracing
- **Cleanup Command**: Management command to clean up stale worker registrations

## Installation

### From Git Repository (Development)

```bash
# Install directly from GitHub
pip install git+https://github.com/drvmukhin/djquark_workers.git

# Or install a specific branch/tag
pip install git+https://github.com/drvmukhin/djquark_workers.git@main
pip install git+https://github.com/drvmukhin/djquark_workers.git@v0.1.0

# Or clone and install in editable mode for development
git clone git@github.com:drvmukhin/djquark_workers.git
cd djquark_workers
pip install -e .
```

### From PyPI (When Published)

```bash
pip install djquark-workers
```

## Quick Start

### 1. Add to INSTALLED_APPS

```python
# settings.py
INSTALLED_APPS = [
    # ...
    'djquark_workers',
]
```

### 2. Configure Redis Connection

```python
# Option A: Direct Redis URL (recommended)
QUARK_WORKERS_REDIS_URL = "redis://localhost:6379/0"

# Option B: Reuse Django cache backend
QUARK_WORKERS_REDIS_CACHE = "default"  # Uses CACHES['default']
```

### 3. Register Loggers (Optional)

```python
# settings.py
QUARK_WORKERS_LOGGERS = [
    # Standard loggers
    '',                     # Root logger
    'django',
    'django.request',
    'django.db.backends',
    
    # Your project loggers
    'myapp',
    'myapp.views',
    'myapp.tasks',
    
    # Third-party loggers
    'celery',
    'uvicorn',
]
```

### 4. Include URLs

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path('admin/workers/', include('djquark_workers.urls')),
]
```

### 5. Run Migrations

```bash
python manage.py migrate djquark_workers
```

### 6. Access Admin Panel

Navigate to `/admin/workers/logging/` (requires superuser by default)

## Configuration

All settings use the `QUARK_WORKERS_` prefix:

```python
# settings.py

# Required: Redis connection (one of these)
QUARK_WORKERS_REDIS_URL = "redis://localhost:6379/0"
# OR
QUARK_WORKERS_REDIS_CACHE = "default"

# Optional: Fine-tune behavior
QUARK_WORKERS_CONFIG = {
    'ENABLED': True,                    # Enable/disable worker registry
    'HEARTBEAT_INTERVAL': 30,           # Seconds between heartbeats
    'HEARTBEAT_TTL': 60,                # Seconds before worker considered dead
    'REDIS_PREFIX': 'quark:workers',    # Redis key prefix for workers
    'LOGGING_PREFIX': 'quark:logging',  # Redis key prefix for logging
}

# Optional: Admin panel access control
# 'superuser' (default), 'staff', or custom permission string
QUARK_WORKERS_ADMIN_PERMISSION = 'superuser'

# Optional: Register loggers for dynamic management
QUARK_WORKERS_LOGGERS = [
    ('', 'Root Logger', 'root'),
    ('django', 'Django Core', 'django'),
    ('django.request', 'Django Requests', 'django'),
    ('myapp', 'My Application', 'application'),
    # Format: (logger_name, display_name, category)
    # Categories: 'application', 'django', 'infrastructure', 'root'
]

# Shorthand format (auto-generates display names):
QUARK_WORKERS_LOGGERS = ['', 'django', 'django.request', 'myapp']
```

## Using Worker ID in Logs

Add `{worker_id}` to your logging format:

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{worker_id}] {asctime} {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'filters': {
        'worker_id': {
            '()': 'djquark_workers.logging.WorkerIdFilter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['worker_id'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

Output:
```
[wk-01] 2024-02-28 10:30:00 INFO myapp.views: User logged in
[cw-02] 2024-02-28 10:30:01 INFO myapp.tasks: Task completed
[bt-01] 2024-02-28 10:30:05 INFO celery.beat: Scheduler tick
```

## Worker Types

The package automatically detects the process type:

| Prefix | Type | Description |
|--------|------|-------------|
| `wk-XX` | Web | Gunicorn/Uvicorn web workers |
| `cw-XX` | Celery | Celery task workers |
| `bt-XX` | Beat | Celery beat scheduler |
| `bot-XX` | Bot | Discord bots or similar |

### Development Server Support

The package **also works with Django's development server** (`manage.py runserver`). 
When running in development mode, a single worker will be registered as `wk-01`.

This is useful for:
- Testing worker registration locally
- Verifying logging configuration changes
- Development/debugging with consistent log formats

The package automatically handles Django's auto-reloader (only registers once, not twice).

## Management Commands

### Cleanup Workers

```bash
# List all registered workers (dry run)
python manage.py cleanup_workers --dry-run

# Clean up stale workers (those without active heartbeat)
python manage.py cleanup_workers

# Force remove specific workers by ID
python manage.py cleanup_workers --force wk-10 wk-11

# Force remove using wildcards
python manage.py cleanup_workers --force "wk-*"      # All web workers
python manage.py cleanup_workers --force "cw-*"      # All celery workers

# Clean up ALL workers (useful before fresh deployment)
python manage.py cleanup_workers --all

# Verbose output with worker details
python manage.py cleanup_workers --verbose
```

## API Usage

### Worker Registry

```python
from djquark_workers.services import WorkerRegistry

# Get current worker ID
worker_id = WorkerRegistry.get_worker_id()  # "wk-01"

# Get all active workers
workers = WorkerRegistry.get_active_workers()  # ["wk-01", "wk-02", "cw-01"]

# Get workers by type
by_type = WorkerRegistry.get_workers_by_type()
# {'web': ['wk-01', 'wk-02'], 'celery': ['cw-01'], 'beat': ['bt-01'], 'discord_bot': []}

# Get worker count
count = WorkerRegistry.get_worker_count()  # 4

# Get worker info
info = WorkerRegistry.get_worker_info('wk-01')
# {'pid': '12345', 'hostname': 'server1', 'started_at': '...', 'process_type': 'web'}
```

### Logging Manager

```python
from djquark_workers.services import LoggingManager

# Set a logger's level (broadcasts to all workers)
LoggingManager.set_level('myapp', 'DEBUG')

# Set multiple levels at once
LoggingManager.set_multiple_levels({
    'myapp': 'DEBUG',
    'django.db.backends': 'WARNING',
})

# Get current level for a logger
level = LoggingManager.get_level('myapp')  # "DEBUG"

# Get all configured levels
all_levels = LoggingManager.get_all_levels()

# Reset to defaults from settings.py
LoggingManager.reset_to_defaults()
```

## Customizing the Admin Template

Override the default template by creating your own:

```html
<!-- templates/djquark_workers/logging_settings.html -->
{% extends "djquark_workers/logging_settings.html" %}

{% block extra_css %}
<style>
    /* Your custom styles */
    .logging-page { max-width: 1200px; }
</style>
{% endblock %}
```

Or completely replace it:

```html
<!-- templates/djquark_workers/logging_settings.html -->
{% extends "admin/base_site.html" %}

{% block content %}
<!-- Your custom admin panel -->
{% endblock %}
```

## Requirements

- Python 3.9+
- Django 3.2+
- Redis 4.0+

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.


