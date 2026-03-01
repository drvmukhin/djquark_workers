# djquark-workers Functional Specification

# djquark-workers Functional Specification

**Version:** 0.1.0  
**Last Updated:** 2026-02-28  
**Author:** Vasily

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Core Components](#3-core-components)
4. [Data Flow](#4-data-flow)
5. [Redis Data Structures](#5-redis-data-structures)
6. [Configuration Reference](#6-configuration-reference)
7. [Startup Sequence](#7-startup-sequence)
8. [Pub/Sub Protocol](#8-pubsub-protocol)
9. [Database Schema](#9-database-schema)
10. [Error Handling](#10-error-handling)
11. [Troubleshooting Guide](#11-troubleshooting-guide)
12. [Extending the Package](#12-extending-the-package)
13. [Testing](#13-testing)

---

## 1. Overview

### 1.1 Purpose

`djquark-workers` is a Django package that provides:

1. **Worker Registration**: Unique identification and tracking of distributed worker processes (Gunicorn, Uvicorn, Celery, etc.)
2. **Dynamic Logging Management**: Runtime log level changes without server restart, synchronized across all workers via Redis pub/sub
3. **Worker ID in Logs**: A logging filter to include worker ID in log messages for traceability

### 1.2 Key Design Principles

- **Zero-configuration default**: Works out of the box with sensible defaults
- **Non-blocking startup**: All initialization happens in background threads
- **Graceful degradation**: Falls back safely if Redis is unavailable
- **Cross-process synchronization**: Uses Redis pub/sub for real-time updates

### 1.3 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| Django | ≥3.2 | Web framework |
| redis | ≥4.0 | Redis client for worker registry and pub/sub |

Optional:
- `django-redis` ≥5.0 - If using Django cache backend for Redis connection

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Django Application                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │   Web       │  │   Celery    │  │   Celery    │  │  Discord   │ │
│  │  Worker 1   │  │  Worker 1   │  │    Beat     │  │    Bot     │ │
│  │   (wk-01)   │  │   (cw-01)   │  │   (bt-01)   │  │  (bot-01)  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘ │
│         │                │                │                │        │
│         └────────────────┴────────────────┴────────────────┘        │
│                                   │                                  │
│                    ┌──────────────┴──────────────┐                  │
│                    │      WorkerRegistry         │                  │
│                    │   LoggingSubscriber         │                  │
│                    │    LoggingManager           │                  │
│                    └──────────────┬──────────────┘                  │
│                                   │                                  │
└───────────────────────────────────┼──────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │             Redis             │
                    │  ┌─────────────────────────┐  │
                    │  │  Worker Registry (SET)  │  │
                    │  │  Heartbeats (STRING)    │  │
                    │  │  Worker Info (HASH)     │  │
                    │  │  Logging Config (CACHE) │  │
                    │  │  Pub/Sub Channel        │  │
                    │  └─────────────────────────┘  │
                    └───────────────────────────────┘
```

### 2.2 Component Interactions

```
┌─────────────────────────────────────────────────────────────────┐
│                      Admin Panel (Browser)                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP POST
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                        views.py                                  │
│                    logging_settings()                            │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────────┐ ┌───────────────┐ ┌───────────────────┐
│  LoggingConfig  │ │LoggingManager │ │  WorkerRegistry   │
│    (Model)      │ │  set_level()  │ │ get_active_workers│
│  save to DB     │ │               │ │                   │
└────────┬────────┘ └───────┬───────┘ └───────────────────┘
         │                  │
         │                  ▼
         │          ┌───────────────────┐
         │          │  Redis Pub/Sub    │
         │          │  PUBLISH message  │
         │          └─────────┬─────────┘
         │                    │
         │    ┌───────────────┼───────────────┐
         │    ▼               ▼               ▼
         │ ┌─────────┐   ┌─────────┐   ┌─────────┐
         │ │ wk-01   │   │ wk-02   │   │ cw-01   │
         │ │Subscriber│   │Subscriber│   │Subscriber│
         │ └────┬────┘   └────┬────┘   └────┬────┘
         │      │             │             │
         │      ▼             ▼             ▼
         │  Apply log     Apply log     Apply log
         │  level change  level change  level change
         │
         ▼
    PostgreSQL
    (Persistent)
```

---

## 3. Core Components

### 3.1 WorkerRegistry (`services/worker_registry.py`)

**Purpose**: Manages worker identification and registration in Redis.

**Key Class**: `WorkerRegistry` (class methods only, no instantiation needed)

**State Variables** (class-level):
```python
_worker_id: Optional[str] = None      # Current worker's ID (e.g., "wk-01")
_heartbeat_thread: Optional[Thread]   # Background heartbeat thread
_running: bool = False                # Heartbeat thread running flag
_registered: bool = False             # Registration status
_process_type: str = 'unknown'        # 'web', 'celery', 'beat', 'discord_bot'
```

**Key Methods**:

| Method | Description | Thread-Safe |
|--------|-------------|-------------|
| `register()` | Register worker, start heartbeat | Yes (uses Redis SETNX) |
| `unregister()` | Remove worker from registry | Yes |
| `get_worker_id()` | Get current worker's ID | Yes (read-only) |
| `get_active_workers()` | List all registered workers | Yes |
| `get_workers_by_type()` | Group workers by type | Yes |
| `get_worker_count()` | Count active workers | Yes |
| `get_worker_info(id)` | Get worker metadata | Yes |
| `_cleanup_stale_workers()` | Remove expired workers | Yes |

**Worker ID Assignment Algorithm**:
1. Detect process type (web/celery/beat/bot)
2. Get all existing workers from Redis SET
3. Find lowest available number for this type
4. Atomically claim using `SETNX` on heartbeat key
5. Add to workers SET
6. If race condition, retry up to 10 times
7. Fallback: use PID-based ID

### 3.2 LoggingManager (`services/logging_manager.py`)

**Purpose**: Manages dynamic logging configuration with cross-worker synchronization.

**Key Class**: `LoggingManager` (class methods only)

**Key Methods**:

| Method | Description | Broadcasts |
|--------|-------------|------------|
| `get_level(name)` | Get logger's current level | No |
| `get_effective_level(name)` | Get effective level (incl. parent) | No |
| `get_all_levels()` | Get all configurable loggers' levels | No |
| `set_level(name, level)` | Set a logger's level | Yes (default) |
| `set_multiple_levels(dict)` | Set multiple levels | Yes (default) |
| `apply_saved_config()` | Apply DB/cache config on startup | No |
| `reset_to_defaults()` | Reset to settings.py levels | Yes (default) |

**Broadcast Message Format**:
```json
{
    "action": "set_level|set_multiple|reset",
    "sender": "wk-01",
    "timestamp": "2026-02-28T10:30:00Z",
    "payload": {
        "logger_name": "myapp",
        "level": "DEBUG"
    }
}
```

### 3.3 LoggingSubscriber (`services/logging_subscriber.py`)

**Purpose**: Redis pub/sub listener for logging configuration updates.

**Key Class**: `LoggingSubscriber` (class methods only)

**State Variables**:
```python
_thread: Optional[Thread]    # Listener thread
_running: bool = False       # Thread running flag
_pubsub: Any = None          # Redis pubsub object
_restart_count: int = 0      # Auto-restart counter
_max_restarts: int = 5       # Max restart attempts
```

**Behavior**:
- Runs as daemon thread (dies with main process)
- Auto-restarts on failure with exponential backoff
- Ignores messages from self (prevents loops)
- Message timeout: 1 second (allows graceful shutdown)

### 3.4 WorkerIdFilter (`logging.py`)

**Purpose**: Logging filter that adds `worker_id` to log records.

**Usage in Format String**:
```python
'format': '[{worker_id}] {levelname} {name}: {message}'
```

**Caching**:
- First lookup caches the worker ID
- Use `WorkerIdFilter.reset_cache()` if worker re-registers

### 3.5 LoggingConfig (`models.py`)

**Purpose**: Persistent storage of logging configuration.

**Model Fields**:
```python
logger_name: CharField(max_length=100, unique=True)
level: CharField(choices=LogLevel.choices)
description: CharField(max_length=255, blank=True)
is_active: BooleanField(default=True)
updated_at: DateTimeField(auto_now=True)
updated_by: ForeignKey(AUTH_USER_MODEL, null=True)
```

**Key Methods**:
- `get_all_active()` → `Dict[str, str]`
- `set_logger_level(name, level, user=None)` → `LoggingConfig`
- `reset_logger(name)` → Deactivates config
- `reset_all()` → Deactivates all configs

---

## 4. Data Flow

### 4.1 Worker Registration Flow

```
Django Startup
      │
      ▼
AppConfig.ready()
      │
      ├── Skip if: management command (migrate, shell, etc.)
      ├── Skip if: dev server parent process (RUN_MAIN not set)
      │
      ▼
Background Thread Started
      │
      ▼
WorkerRegistry.register()
      │
      ├── 1. _cleanup_stale_workers()
      │       └── Remove workers without heartbeat
      │
      ├── 2. _assign_worker_id()
      │       ├── Detect process type
      │       ├── Find lowest available number
      │       └── Claim atomically with SETNX
      │
      ├── 3. _store_worker_info()
      │       └── Store PID, hostname, start time
      │
      └── 4. _start_heartbeat()
              └── Start background thread
      
LoggingSubscriber.start()
      │
      └── Subscribe to pub/sub channel

(1 second delay)
      │
      ▼
LoggingManager.apply_saved_config()
      │
      ├── Load from Redis cache
      └── Load from database (authoritative)
```

### 4.2 Log Level Change Flow

```
Admin Panel: Change logger level
      │
      ▼
views.logging_settings() [POST]
      │
      ├── LoggingConfig.set_logger_level()
      │       └── Save to database
      │
      └── LoggingManager.set_level()
              │
              ├── Apply to local Python logging
              │
              ├── _save_to_cache()
              │       └── Update Redis cache
              │
              └── _broadcast_change()
                      │
                      ▼
              Redis PUBLISH to channel
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      [wk-01]     [wk-02]     [cw-01]
    Subscriber   Subscriber  Subscriber
          │           │           │
          ▼           ▼           ▼
    (Skip self)  Apply to    Apply to
                 logging     logging
```

---

## 5. Redis Data Structures

### 5.1 Keys and Patterns

| Key Pattern | Type | TTL | Description |
|-------------|------|-----|-------------|
| `{prefix}:set` | SET | None | All registered worker IDs |
| `{prefix}:{worker_id}:heartbeat` | STRING | 60s | Heartbeat timestamp |
| `{prefix}:{worker_id}:info` | HASH | 60s | Worker metadata |
| `{logging_prefix}:config` | STRING | None | Cached logging config (JSON) |
| `{logging_prefix}:updates` | PUBSUB | N/A | Log level change channel |

Default prefixes:
- `prefix` = `quark:workers`
- `logging_prefix` = `quark:logging`

### 5.2 Workers SET

```redis
SMEMBERS quark:workers:set
# Returns: ["wk-01", "wk-02", "cw-01", "bt-01"]
```

### 5.3 Heartbeat Key

```redis
GET quark:workers:wk-01:heartbeat
# Returns: "2026-02-28T10:30:00.123456+00:00"

TTL quark:workers:wk-01:heartbeat
# Returns: 45 (seconds remaining)
```

### 5.4 Worker Info Hash

```redis
HGETALL quark:workers:wk-01:info
# Returns:
# {
#   "pid": "12345",
#   "hostname": "server1",
#   "started_at": "2026-02-28T10:00:00.000000+00:00",
#   "process_type": "web"
# }
```

### 5.5 Logging Config Cache

```redis
GET quark:logging:config
# Returns (JSON string):
# {"myapp": "DEBUG", "django.db.backends": "WARNING"}
```

---

## 6. Configuration Reference

### 6.1 Settings Hierarchy

```python
# 1. Direct Redis URL (highest priority)
QUARK_WORKERS_REDIS_URL = "redis://localhost:6379/0"

# 2. Django cache backend
QUARK_WORKERS_REDIS_CACHE = "default"  # Uses CACHES['default']['LOCATION']

# 3. Project-level REDIS_URL
REDIS_URL = "redis://localhost:6379/0"

# 4. Default fallback
# "redis://localhost:6379/0"
```

### 6.2 Full Configuration Options

```python
# Main config dict
QUARK_WORKERS_CONFIG = {
    'ENABLED': True,              # Master switch
    'HEARTBEAT_INTERVAL': 30,     # Seconds between heartbeats
    'HEARTBEAT_TTL': 60,          # Seconds before considered dead
    'REDIS_PREFIX': 'quark:workers',
    'LOGGING_PREFIX': 'quark:logging',
    'ADMIN_PERMISSION': 'superuser',  # 'superuser'|'staff'|'perm.name'
}

# Loggers configuration
QUARK_WORKERS_LOGGERS = [
    # Full tuple format
    ('myapp', 'My Application', 'application'),
    
    # Short tuple (auto-categorize)
    ('myapp.views', 'Views'),
    
    # String only (auto-generate display name and category)
    'myapp.models',
]
```

### 6.3 Settings Object (`conf.py`)

The `QuarkWorkersSettings` class provides lazy access to all settings:

```python
from djquark_workers.conf import settings

settings.ENABLED              # bool
settings.HEARTBEAT_INTERVAL   # int
settings.HEARTBEAT_TTL        # int
settings.REDIS_PREFIX         # str
settings.LOGGING_PREFIX       # str
settings.ADMIN_PERMISSION     # str
settings.REDIS_URL            # str (computed)
settings.CONFIGURABLE_LOGGERS # List[Tuple[str, str, str]]
settings.LOG_LEVELS           # List[Tuple[str, str]]
```

---

## 7. Startup Sequence

### 7.1 Django Development Server

```
manage.py runserver
       │
       ▼
Parent Process (auto-reloader)
  - RUN_MAIN not set
  - AppConfig.ready() called
  - _is_dev_server() = True
  - Registration SKIPPED
       │
       ▼ (spawns child)
       
Child Process
  - RUN_MAIN = 'true'
  - AppConfig.ready() called
  - _is_dev_server() = True
  - is_reloader_child = True
  - Registration PROCEEDS
       │
       ▼
Worker registered as wk-01
```

### 7.2 Gunicorn/Uvicorn

```
gunicorn myapp.wsgi:application -w 4
       │
       ▼
Master Process
  - Does NOT run Django app
       │
       ├── Fork Worker 1
       ├── Fork Worker 2
       ├── Fork Worker 3
       └── Fork Worker 4
       
Each Worker Process:
  - Loads Django app
  - AppConfig.ready() called
  - _is_dev_server() = False
  - Registration PROCEEDS
       │
       ▼
Workers registered as wk-01, wk-02, wk-03, wk-04
```

### 7.3 Celery Worker

```
celery -A myapp worker -c 4
       │
       ▼
Main Process (prefork pool)
  - Loads Django app ONCE
  - AppConfig.ready() called
  - Detected as 'celery' worker
  - Registration PROCEEDS
       │
       ▼
Worker registered as cw-01

Note: Celery pool workers (child processes) do NOT
      separately register - only the main worker process.
```

---

## 8. Pub/Sub Protocol

### 8.1 Channel Name

```
{LOGGING_PREFIX}:updates
# Default: quark:logging:updates
```

### 8.2 Message Types

#### set_level
```json
{
    "action": "set_level",
    "sender": "wk-01",
    "timestamp": "2026-02-28T10:30:00.000000+00:00",
    "payload": {
        "logger_name": "myapp",
        "level": "DEBUG"
    }
}
```

#### set_multiple
```json
{
    "action": "set_multiple",
    "sender": "wk-01",
    "timestamp": "2026-02-28T10:30:00.000000+00:00",
    "payload": {
        "levels": {
            "myapp": "DEBUG",
            "django.db.backends": "WARNING"
        }
    }
}
```

#### reset
```json
{
    "action": "reset",
    "sender": "wk-01",
    "timestamp": "2026-02-28T10:30:00.000000+00:00",
    "payload": {}
}
```

### 8.3 Message Handling Rules

1. **Self-skip**: Messages from `sender == current_worker_id` are ignored
2. **Unknown action**: Logged as warning, not processed
3. **Invalid JSON**: Logged as warning, not processed
4. **Processing error**: Logged as error, subscriber continues

---

## 9. Database Schema

### 9.1 Table: `djquark_logging_config`

```sql
CREATE TABLE djquark_logging_config (
    id BIGSERIAL PRIMARY KEY,
    logger_name VARCHAR(100) UNIQUE NOT NULL,
    level VARCHAR(10) NOT NULL DEFAULT 'INFO',
    description VARCHAR(255) DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_by_id BIGINT REFERENCES auth_user(id) ON DELETE SET NULL
);

CREATE INDEX idx_logging_config_logger_name ON djquark_logging_config(logger_name);
```

### 9.2 Level Choices

```python
class LogLevel(models.TextChoices):
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'
```

---

## 10. Error Handling

### 10.1 Redis Connection Failure

**During Registration**:
- Falls back to PID-based worker ID: `{prefix}-{PID}`
- Logs warning, continues operation
- No heartbeat thread started

**During Broadcast**:
- Logs warning
- Local change still applied
- Other workers won't receive update

**During Subscriber**:
- Auto-restart with exponential backoff (1s, 2s, 4s, ..., max 30s)
- Max 5 restart attempts before giving up
- Logs errors at each failure

### 10.2 Database Failure

**During apply_saved_config()**:
- Falls back to Redis cache if available
- Logs warning, continues with cached/default config

**During set_logger_level()**:
- Exception propagates to view
- View returns error response
- Runtime change may still succeed

### 10.3 Process Detection Failure

**If process type can't be detected**:
- Defaults to 'web' worker type (`wk-XX`)
- Logs debug message

---

## 11. Troubleshooting Guide

### 11.1 Workers Not Registering

**Symptoms**: No workers in admin panel, `cleanup_workers --dry-run` shows nothing

**Check**:
```bash
# Verify Redis connection
python manage.py shell -c "
from djquark_workers.services.worker_registry import _get_redis_client
client = _get_redis_client()
print(client.ping())
"

# Check if app is enabled
python manage.py shell -c "
from djquark_workers.conf import settings
print(f'Enabled: {settings.ENABLED}')
print(f'Redis URL: {settings.REDIS_URL}')
"
```

**Common Causes**:
1. `QUARK_WORKERS_CONFIG['ENABLED'] = False`
2. Redis not running or wrong URL
3. Running a skip command (migrate, shell, etc.)

### 11.2 Log Level Changes Not Propagating

**Symptoms**: Changed level in admin, but other workers don't reflect it

**Check**:
```bash
# Verify subscriber is running
python manage.py shell -c "
from djquark_workers.services.logging_subscriber import LoggingSubscriber
print(f'Running: {LoggingSubscriber.is_running()}')
"

# Check Redis pub/sub
redis-cli PUBSUB NUMSUB quark:logging:updates
```

**Common Causes**:
1. Subscriber crashed and exceeded max restarts
2. Redis connection lost after startup
3. Different `LOGGING_PREFIX` between workers

### 11.3 Duplicate Worker IDs

**Symptoms**: Multiple workers with same ID, or gaps in numbering

**Check**:
```bash
python manage.py cleanup_workers --verbose --dry-run
```

**Fix**:
```bash
# Clean up all stale workers
python manage.py cleanup_workers

# Or force-clean specific IDs
python manage.py cleanup_workers --force wk-01 wk-02
```

**Cause**: Workers died without proper unregistration (SIGKILL, crash)

### 11.4 High Redis Memory Usage

**Symptoms**: Redis memory growing over time

**Check**:
```bash
redis-cli KEYS "quark:*" | wc -l
```

**Fix**: Run periodic cleanup
```bash
# In crontab or celery beat
python manage.py cleanup_workers
```

### 11.5 Debugging Worker Registration

Enable debug logging for the package:
```python
LOGGING = {
    'loggers': {
        'djquark_workers': {
            'level': 'DEBUG',
            'handlers': ['console'],
        },
    },
}
```

---

## 12. Extending the Package

### 12.1 Adding New Worker Types

**Step 1**: Add constant in `worker_registry.py`:
```python
WORKER_TYPE_MYSERVICE = 'ms'  # ms-01, ms-02, etc.
```

**Step 2**: Update `_detect_process_type()`:
```python
def _detect_process_type() -> Tuple[str, str]:
    argv_str = ' '.join(sys.argv).lower()
    
    # Add detection for your service
    if 'run_myservice' in argv_str:
        return (WORKER_TYPE_MYSERVICE, 'myservice')
    
    # ... existing detection
```

**Step 3**: Update `get_workers_by_type()`:
```python
result = {
    'web': [],
    'celery': [],
    'beat': [],
    'discord_bot': [],
    'myservice': [],  # Add new type
}

# Add matching logic
elif w.startswith('ms-'):
    result['myservice'].append(w)
```

### 12.2 Adding New Broadcast Actions

**Step 1**: Add broadcast method in `LoggingManager`:
```python
@classmethod
def _broadcast_custom_action(cls, data: dict) -> None:
    message = json.dumps({
        'action': 'custom_action',
        'sender': WorkerRegistry.get_worker_id(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'payload': data
    })
    redis_client = _get_redis_client()
    redis_client.publish(_get_logging_channel(), message)
```

**Step 2**: Handle in `LoggingSubscriber._handle_message()`:
```python
elif action == 'custom_action':
    # Process custom action
    custom_data = payload.get('payload', {})
    handle_custom_action(custom_data)
```

### 12.3 Custom Admin Permission

```python
# settings.py
QUARK_WORKERS_ADMIN_PERMISSION = 'myapp.can_manage_logging'

# Then assign permission to users/groups via Django admin
```

### 12.4 Custom Template Integration

Override the template to integrate with your admin panel:

```html
<!-- templates/djquark_workers/logging_settings.html -->
{% extends "my_admin/base.html" %}

{% block extra_css %}
<link rel="stylesheet" href="{% static 'my_admin/logging.css' %}">
{% endblock %}

{% block content %}
<div class="my-admin-wrapper">
    {{ block.super }}
</div>
{% endblock %}
```

---

## 13. Testing

### 13.1 Running Tests

```bash
cd .quark_workers
pip install -e ".[dev]"
pytest
```

### 13.2 Test Configuration

Tests use `tests/settings.py` with:
- SQLite in-memory database
- Separate Redis database (DB 15)
- Shorter heartbeat intervals for faster tests

### 13.3 Mocking Redis

For unit tests without Redis:
```python
from unittest.mock import patch, MagicMock

@patch('djquark_workers.services.worker_registry._get_redis_client')
def test_registration(self, mock_redis):
    mock_client = MagicMock()
    mock_redis.return_value = mock_client
    mock_client.smembers.return_value = set()
    mock_client.setnx.return_value = True
    
    # Test code here
```

### 13.4 Integration Tests

For integration tests with real Redis:
```python
import pytest

@pytest.mark.skipif(
    not redis_available(),
    reason="Redis not available"
)
def test_full_registration_cycle():
    from djquark_workers.services.worker_registry import WorkerRegistry
    
    worker_id = WorkerRegistry.register()
    assert worker_id in WorkerRegistry.get_active_workers()
    
    WorkerRegistry.unregister()
    assert worker_id not in WorkerRegistry.get_active_workers()
```

---

## Appendix A: File Structure

```
djquark_workers/
├── __init__.py           # Package exports, version
├── apps.py               # Django AppConfig (startup logic)
├── conf.py               # Settings management
├── models.py             # LoggingConfig model
├── admin.py              # Django admin registration
├── urls.py               # URL routing
├── views.py              # Admin panel views
├── logging.py            # WorkerIdFilter
│
├── services/
│   ├── __init__.py       # Service exports
│   ├── worker_registry.py    # Worker registration
│   ├── logging_manager.py    # Logging level management
│   └── logging_subscriber.py # Redis pub/sub listener
│
├── management/
│   └── commands/
│       └── cleanup_workers.py
│
└── templates/
    └── djquark_workers/
        ├── logging_settings.html
        └── worker_status.html
```

---

## Appendix B: Redis Commands Reference

```bash
# List all workers
redis-cli SMEMBERS quark:workers:set

# Check specific worker heartbeat
redis-cli GET quark:workers:wk-01:heartbeat
redis-cli TTL quark:workers:wk-01:heartbeat

# Get worker info
redis-cli HGETALL quark:workers:wk-01:info

# View logging config cache
redis-cli GET quark:logging:config

# Monitor pub/sub messages
redis-cli SUBSCRIBE quark:logging:updates

# Count subscribers
redis-cli PUBSUB NUMSUB quark:logging:updates

# Clean up all quark keys (DANGER!)
redis-cli KEYS "quark:*" | xargs redis-cli DEL
```

---

## Appendix C: Sequence Diagrams

### C.1 Worker Startup

```
┌─────────┐     ┌──────────────┐     ┌───────┐     ┌──────────┐
│ Django  │     │WorkerRegistry│     │ Redis │     │Subscriber│
└────┬────┘     └──────┬───────┘     └───┬───┘     └────┬─────┘
     │                 │                 │              │
     │ ready()         │                 │              │
     │────────────────>│                 │              │
     │                 │                 │              │
     │                 │ SMEMBERS        │              │
     │                 │────────────────>│              │
     │                 │                 │              │
     │                 │ SETNX heartbeat │              │
     │                 │────────────────>│              │
     │                 │                 │              │
     │                 │ SADD workers    │              │
     │                 │────────────────>│              │
     │                 │                 │              │
     │                 │ HSET info       │              │
     │                 │────────────────>│              │
     │                 │                 │              │
     │                 │ start()         │              │
     │                 │────────────────────────────────>
     │                 │                 │              │
     │                 │                 │  SUBSCRIBE   │
     │                 │                 │<─────────────│
     │                 │                 │              │
     │<────────────────│                 │              │
     │  worker_id      │                 │              │
```

### C.2 Log Level Change Broadcast

```
┌──────┐    ┌──────┐    ┌───────────────┐    ┌───────┐    ┌──────┐    ┌──────┐
│Admin │    │Views │    │LoggingManager │    │ Redis │    │wk-02 │    │cw-01 │
└──┬───┘    └──┬───┘    └──────┬────────┘    └───┬───┘    └──┬───┘    └──┬───┘
   │           │               │                 │           │           │
   │ POST      │               │                 │           │           │
   │──────────>│               │                 │           │           │
   │           │               │                 │           │           │
   │           │ set_level()   │                 │           │           │
   │           │──────────────>│                 │           │           │
   │           │               │                 │           │           │
   │           │               │ SET cache       │           │           │
   │           │               │────────────────>│           │           │
   │           │               │                 │           │           │
   │           │               │ PUBLISH         │           │           │
   │           │               │────────────────>│           │           │
   │           │               │                 │           │           │
   │           │               │                 │ message   │           │
   │           │               │                 │──────────>│           │
   │           │               │                 │           │           │
   │           │               │                 │ message   │           │
   │           │               │                 │──────────────────────>│
   │           │               │                 │           │           │
   │           │               │                 │           │ apply     │
   │           │               │                 │           │ level     │
   │           │               │                 │           │           │
   │           │<──────────────│                 │           │           │
   │<──────────│               │                 │           │           │
   │ success   │               │                 │           │           │
```


