# djquark-workers Quick Reference

## Common Operations

### Check Worker Status

```bash
# List all registered workers
python manage.py cleanup_workers --dry-run

# With detailed info (PID, hostname, start time)
python manage.py cleanup_workers --dry-run --verbose
```

### Clean Up Workers

```bash
# Remove stale workers (no heartbeat OR dead PID)
python manage.py cleanup_workers

# Preview what would be removed (dry run)
python manage.py cleanup_workers --dry-run

# With detailed info — shows PID, hostname, OOM status
python manage.py cleanup_workers --dry-run --verbose

# Force remove specific workers
python manage.py cleanup_workers --force wk-05 wk-06

# Remove all web workers
python manage.py cleanup_workers --force "wk-*"

# Remove ALL workers (before deployment)
python manage.py cleanup_workers --all
```

### Recover from OOM-Killed Workers

When a worker is killed by SIGKILL (OOM), its slot stays occupied in Redis
until the heartbeat TTL expires (default 60s). To reclaim slots immediately:

```bash
# Detects dead PIDs even if heartbeat TTL hasn't expired yet
python manage.py cleanup_workers

# Automate via cron (every minute)
* * * * * cd /path/to/project && python manage.py cleanup_workers --quiet
```

### Debug Redis State

```bash
# Connect to Redis CLI
redis-cli

# List all workers
SMEMBERS quark:workers:set

# Check worker heartbeat
GET quark:workers:wk-01:heartbeat
TTL quark:workers:wk-01:heartbeat

# Get worker info
HGETALL quark:workers:wk-01:info

# View cached logging config
GET quark:logging:config

# Monitor real-time pub/sub messages
SUBSCRIBE quark:logging:updates
```

### Django Shell Commands

```python
# Get current worker ID
from djquark_workers.services import WorkerRegistry
WorkerRegistry.get_worker_id()

# List all active workers
WorkerRegistry.get_active_workers()

# Get workers by type
WorkerRegistry.get_workers_by_type()

# Set a log level (broadcasts to all workers)
from djquark_workers.services import LoggingManager
LoggingManager.set_level('myapp', 'DEBUG')

# Get current log levels
LoggingManager.get_all_levels()

# Reset to defaults
LoggingManager.reset_to_defaults()
```

## Configuration Snippets

### Minimal Setup

```python
# settings.py
INSTALLED_APPS = [
    # ...
    'djquark_workers',
]

QUARK_WORKERS_REDIS_URL = "redis://localhost:6379/0"
```

### Full Configuration

```python
# settings.py
QUARK_WORKERS_REDIS_URL = "redis://localhost:6379/0"

QUARK_WORKERS_CONFIG = {
    'ENABLED': True,
    'HEARTBEAT_INTERVAL': 30,
    'HEARTBEAT_TTL': 60,
    'REDIS_PREFIX': 'myapp:workers',
    'LOGGING_PREFIX': 'myapp:logging',
    'ADMIN_PERMISSION': 'superuser',
}

QUARK_WORKERS_LOGGERS = [
    ('', 'Root Logger', 'root'),
    ('django', 'Django Core', 'django'),
    ('django.request', 'Django Requests', 'django'),
    ('myapp', 'My Application', 'application'),
    ('myapp.views', 'Views', 'application'),
    ('myapp.tasks', 'Celery Tasks', 'application'),
    ('celery', 'Celery', 'infrastructure'),
    ('uvicorn', 'Uvicorn', 'infrastructure'),
]
```

### Logging Configuration with Worker ID

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
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
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### URL Configuration

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    # Standard Django admin
    path('admin/', admin.site.urls),
    
    # djquark-workers admin panel
    path('admin/workers/', include('djquark_workers.urls')),
]
```

## Worker ID Prefixes

| Prefix | Type | Example |
|--------|------|---------|
| `wk-` | Web worker (Gunicorn/Uvicorn) | `wk-01`, `wk-02` |
| `cw-` | Celery worker | `cw-01`, `cw-02` |
| `bt-` | Celery beat scheduler | `bt-01` |
| `bot-` | Discord bot | `bot-01` |

## Log Levels

| Level | Value | Use Case |
|-------|-------|----------|
| DEBUG | 10 | Detailed diagnostic info |
| INFO | 20 | General operational info |
| WARNING | 30 | Something unexpected |
| ERROR | 40 | Serious problem |
| CRITICAL | 50 | Program may not continue |

## URL Endpoints

| URL | View | Description |
|-----|------|-------------|
| `/admin/workers/logging/` | `logging_settings` | Main logging config UI |
| `/admin/workers/logging/set-level/` | `logging_set_level` | AJAX API for single level |
| `/admin/workers/logging/reset/` | `logging_reset_all` | AJAX API to reset all |
| `/admin/workers/status/` | `worker_status` | Worker status page |
| `/admin/workers/status/api/` | `worker_status_api` | Worker status JSON API |

## Troubleshooting

### Workers not appearing?

1. Check Redis connection:
   ```python
   from djquark_workers.conf import settings
   print(settings.REDIS_URL)
   ```

2. Check if enabled:
   ```python
   from djquark_workers.conf import settings
   print(settings.ENABLED)
   ```

3. Check Redis directly:
   ```bash
   redis-cli SMEMBERS quark:workers:set
   ```

### Log levels not syncing?

1. Check subscriber is running:
   ```python
   from djquark_workers.services import LoggingSubscriber
   print(LoggingSubscriber.is_running())
   ```

2. Monitor pub/sub:
   ```bash
   redis-cli SUBSCRIBE quark:logging:updates
   ```

### Stale workers?

```bash
python manage.py cleanup_workers
```

### Reset everything?

```bash
# Clean all workers
python manage.py cleanup_workers --all

# Reset logging to defaults (via Django shell)
from djquark_workers.services import LoggingManager
LoggingManager.reset_to_defaults()
```

