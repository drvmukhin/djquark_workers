# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

