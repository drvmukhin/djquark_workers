"""
Management command to clean up stale worker registrations from Redis.

Usage:
    # List all registered workers (dry run)
    python manage.py cleanup_workers --dry-run

    # Clean up stale workers (those without active heartbeat)
    python manage.py cleanup_workers

    # Force remove specific workers by ID
    python manage.py cleanup_workers --force wk-10 wk-11 wk-12

    # Force remove using wildcards (supports * and ?)
    python manage.py cleanup_workers --force "wk-*"      # All web workers
    python manage.py cleanup_workers --force "wk-1?"     # wk-10 through wk-19
    python manage.py cleanup_workers --force "cw-*"      # All celery workers

    # Clean up ALL workers (useful before fresh deployment)
    python manage.py cleanup_workers --all
"""
import fnmatch
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Clean up stale worker registrations from Redis'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually removing anything',
        )
        parser.add_argument(
            '--force',
            nargs='+',
            metavar='WORKER_ID',
            help='Force remove specific worker IDs or patterns (e.g., wk-10 wk-11 or "wk-*" for wildcards)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Remove ALL worker registrations (use before fresh deployment)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about each worker',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force_remove = options.get('force')
        remove_all = options['all']
        verbose = options['verbose']

        # Import here to ensure Django is fully loaded
        from djquark_workers.conf import settings as quark_settings
        from djquark_workers.services.worker_registry import (
            _get_redis_client,
            _get_redis_keys,
            WorkerRegistry,
        )

        try:
            redis_client = _get_redis_client()
        except Exception as e:
            raise CommandError(f"Could not connect to Redis: {e}")

        keys = _get_redis_keys()

        # Get all registered workers
        workers = redis_client.smembers(keys['WORKERS_SET'])
        worker_list = sorted([
            w.decode() if isinstance(w, bytes) else w
            for w in workers
        ])

        if not worker_list:
            self.stdout.write(self.style.SUCCESS("No workers registered in Redis."))
            return

        self.stdout.write(f"\nRegistered workers: {len(worker_list)}")
        self.stdout.write("-" * 50)

        # Analyze each worker
        active_workers = []
        stale_workers = []

        for worker_id in worker_list:
            heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=worker_id)
            info_key = keys['WORKER_INFO'].format(worker_id=worker_id)

            has_heartbeat = redis_client.exists(heartbeat_key)
            heartbeat_ttl = redis_client.ttl(heartbeat_key) if has_heartbeat else -2

            # Determine if worker is truly alive
            is_alive = has_heartbeat
            pid_dead = False

            if has_heartbeat:
                # Heartbeat exists, but check if the PID is still running.
                # This catches OOM-killed workers whose TTL hasn't expired.
                pid = WorkerRegistry._get_worker_pid(redis_client, info_key)
                if pid is not None and not WorkerRegistry._is_pid_alive(pid):
                    is_alive = False
                    pid_dead = True

            if is_alive:
                active_workers.append(worker_id)
                status = self.style.SUCCESS("ACTIVE")
                ttl_info = f"(TTL: {heartbeat_ttl}s)"
            elif pid_dead:
                stale_workers.append(worker_id)
                status = self.style.ERROR("STALE (dead PID, likely OOM-killed)")
                ttl_info = f"(heartbeat TTL: {heartbeat_ttl}s remaining)"
            else:
                stale_workers.append(worker_id)
                status = self.style.ERROR("STALE")
                ttl_info = "(no heartbeat)"

            if verbose:
                # Get worker info
                info = redis_client.hgetall(info_key)
                if info:
                    info_decoded = {
                        k.decode() if isinstance(k, bytes) else k:
                        v.decode() if isinstance(v, bytes) else v
                        for k, v in info.items()
                    }
                    pid = info_decoded.get('pid', 'unknown')
                    hostname = info_decoded.get('hostname', 'unknown')
                    started = info_decoded.get('started_at', 'unknown')
                    process_type = info_decoded.get('process_type', 'unknown')
                    self.stdout.write(
                        f"  {worker_id}: {status} {ttl_info}\n"
                        f"           PID: {pid}, Host: {hostname}, Type: {process_type}\n"
                        f"           Started: {started}"
                    )
                else:
                    self.stdout.write(f"  {worker_id}: {status} {ttl_info} (no info)")
            else:
                self.stdout.write(f"  {worker_id}: {status} {ttl_info}")

        self.stdout.write("-" * 50)
        self.stdout.write(
            f"Active: {len(active_workers)}, "
            f"Stale: {len(stale_workers)}"
        )

        # Determine what to remove
        to_remove = []

        if remove_all:
            to_remove = worker_list
            self.stdout.write(self.style.WARNING(
                f"\n--all specified: Will remove ALL {len(to_remove)} workers"
            ))
        elif force_remove:
            # Expand wildcards and collect matching workers
            matched_workers = set()
            unmatched_patterns = []

            for pattern in force_remove:
                # Check if pattern contains wildcards
                if '*' in pattern or '?' in pattern:
                    matches = [w for w in worker_list if fnmatch.fnmatch(w, pattern)]
                    if matches:
                        matched_workers.update(matches)
                    else:
                        unmatched_patterns.append(pattern)
                else:
                    # Exact match
                    if pattern in worker_list:
                        matched_workers.add(pattern)
                    else:
                        unmatched_patterns.append(pattern)

            if unmatched_patterns:
                self.stdout.write(self.style.WARNING(
                    f"\nWarning: No matches for: {', '.join(unmatched_patterns)}"
                ))

            to_remove = sorted(matched_workers)
            if to_remove:
                self.stdout.write(self.style.WARNING(
                    f"\n--force specified: Will remove {len(to_remove)} workers: {', '.join(to_remove)}"
                ))
        else:
            # Default: remove only stale workers
            to_remove = stale_workers
            if to_remove:
                self.stdout.write(self.style.WARNING(
                    f"\nWill remove {len(to_remove)} stale workers"
                ))

        if not to_remove:
            self.stdout.write(self.style.SUCCESS("\nNo workers to clean up."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY RUN] Would remove: {', '.join(to_remove)}"
            ))
            self.stdout.write("Run without --dry-run to actually remove them.")
            return

        # Perform cleanup
        removed_count = 0
        for worker_id in to_remove:
            try:
                heartbeat_key = keys['WORKER_HEARTBEAT'].format(worker_id=worker_id)
                info_key = keys['WORKER_INFO'].format(worker_id=worker_id)

                # Remove from set and delete keys
                redis_client.srem(keys['WORKERS_SET'], worker_id)
                redis_client.delete(heartbeat_key, info_key)

                removed_count += 1
                self.stdout.write(f"  Removed: {worker_id}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"  Failed to remove {worker_id}: {e}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nCleaned up {removed_count} worker(s)."
        ))

        # Show remaining workers
        remaining = redis_client.smembers(keys['WORKERS_SET'])
        remaining_list = sorted([
            w.decode() if isinstance(w, bytes) else w
            for w in remaining
        ])
        if remaining_list:
            self.stdout.write(f"Remaining workers: {', '.join(remaining_list)}")
        else:
            self.stdout.write("No workers remaining in registry.")

