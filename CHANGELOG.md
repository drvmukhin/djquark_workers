# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-21

### Added
- **PID liveness detection** for OOM-killed workers
  - New `WorkerRegistry._is_pid_alive()` static method — probes process existence
    via `os.kill(pid, 0)` without sending a signal
  - New `WorkerRegistry._get_worker_pid()` static method — reads a worker's stored
    PID from its Redis info hash
  - `cleanup_workers` management command now detects workers with a live heartbeat
    but dead PID (e.g. killed by OOM SIGKILL) and marks them as
    `STALE (dead PID, likely OOM-killed)` for removal
- New tests for `_is_pid_alive`, `_get_worker_pid`, and `_cleanup_stale_workers`

### Fixed
- **Phantom worker IDs after OOM kill** (bug_03212026_001): when a worker was
  killed by SIGKILL (OOM), its `atexit` handler never ran, leaving its slot
  occupied in Redis until the heartbeat TTL expired. Replacement workers were
  forced to claim higher-numbered IDs (e.g. `wk-13` instead of `wk-03`).
  The `cleanup_workers` command now catches this immediately via PID checks.

### Design Notes
- PID liveness checks are intentionally kept **out of the worker startup path**
  (`register()` / `_assign_worker_id()`). Scanning other workers' PIDs is not
  a starting worker's responsibility and would add latency proportional to the
  number of active workers.
- The lightweight TTL-based `_cleanup_stale_workers()` remains in `register()`
  to reclaim slots whose heartbeat keys have already expired (essentially free).
- For immediate OOM recovery, run `python manage.py cleanup_workers` (manually
  or via a periodic Celery task / cron job).

## [0.1.0] - 2024-02-28

### Added
- Initial release
- Worker registration with Redis
- Worker heartbeat monitoring
- Dynamic logging level management
- Cross-worker log level synchronization via Redis pub/sub
- Admin panel for logging configuration
- `WorkerIdFilter` for including worker ID in log format
- `cleanup_workers` management command
- Support for multiple worker types: web, celery, beat, bot
- Configurable admin permissions
- Template customization support

