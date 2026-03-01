"""
Admin panel views for djquark-workers.

Provides views for:
- Logging configuration management
- Worker status monitoring
"""

import json
import logging
from functools import wraps

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .models import LoggingConfig
from .services.logging_manager import LoggingManager
from .services.worker_registry import WorkerRegistry
from .conf import settings as quark_settings

logger = logging.getLogger(__name__)


def quark_admin_required(view_func):
    """
    Decorator to check admin permission for quark-workers views.

    Permission is configurable via QUARK_WORKERS_ADMIN_PERMISSION:
    - 'superuser': requires is_superuser (default)
    - 'staff': requires is_staff
    - 'permission.name': requires specific permission
    """
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        permission = quark_settings.ADMIN_PERMISSION

        if permission == 'superuser':
            if not request.user.is_superuser:
                messages.error(request, 'Superuser access required.')
                return redirect('admin:index')
        elif permission == 'staff':
            if not request.user.is_staff:
                messages.error(request, 'Staff access required.')
                return redirect('admin:index')
        else:
            # Custom permission string
            if not request.user.has_perm(permission):
                messages.error(request, f'Permission required: {permission}')
                return redirect('admin:index')

        return view_func(request, *args, **kwargs)
    return wrapper


@quark_admin_required
def logging_settings(request):
    """
    Dynamic logging configuration - change log levels at runtime without restart.

    GET: Display current logging levels for all configurable loggers
    POST: Update logging levels and broadcast to all worker processes
    """
    configurable_loggers = quark_settings.CONFIGURABLE_LOGGERS
    log_levels = quark_settings.LOG_LEVELS

    if request.method == 'POST':
        action = request.POST.get('action', 'update')

        if action == 'reset':
            # Reset all loggers to settings.py defaults
            count = LoggingConfig.reset_all()
            LoggingManager.reset_to_defaults()
            messages.success(request, f'Reset {count} custom logging level(s) to defaults from settings.py')
            return redirect('djquark_workers:logging_settings')

        # Update individual logger levels
        updated_count = 0
        levels_to_apply = {}

        for logger_name, display_name, category in configurable_loggers:
            form_key = f'level_{logger_name}' if logger_name else 'level_root'
            new_level = request.POST.get(form_key)

            if new_level and new_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                # Save to database
                LoggingConfig.set_logger_level(
                    logger_name=logger_name,
                    level=new_level,
                    user=request.user,
                    description=display_name,
                )
                levels_to_apply[logger_name] = new_level
                updated_count += 1

        # Apply all changes and broadcast to workers
        if levels_to_apply:
            LoggingManager.set_multiple_levels(levels_to_apply)
            messages.success(
                request,
                f'Updated {updated_count} logger(s). Changes applied to all workers.'
            )

        return redirect('djquark_workers:logging_settings')

    # GET: Build current state for each logger
    saved_configs = {c.logger_name: c for c in LoggingConfig.objects.all()}
    current_levels = LoggingManager.get_all_levels()

    # Organize loggers by category
    loggers_by_category = {
        'application': [],
        'django': [],
        'infrastructure': [],
        'root': [],
    }

    for logger_name, display_name, category in configurable_loggers:
        saved_config = saved_configs.get(logger_name)
        current_info = current_levels.get(logger_name, {})

        # Use saved level from DB if active (authoritative source),
        # otherwise use current in-memory level
        effective_level = (
            saved_config.level
            if (saved_config and saved_config.is_active)
            else current_info.get('effective_level', 'NOTSET')
        )

        logger_data = {
            'name': logger_name,
            'display_name': display_name,
            'form_key': f'level_{logger_name}' if logger_name else 'level_root',
            'current_level': current_info.get('current_level', 'NOTSET'),
            'effective_level': effective_level,
            'default_level': current_info.get('default_level', 'INFO'),
            'saved_level': saved_config.level if saved_config and saved_config.is_active else None,
            'is_customized': saved_config.is_active if saved_config else False,
            'last_updated': saved_config.updated_at if saved_config else None,
            'updated_by': saved_config.updated_by if saved_config else None,
        }

        if category in loggers_by_category:
            loggers_by_category[category].append(logger_data)
        else:
            loggers_by_category['application'].append(logger_data)

    # Get active workers info grouped by type
    try:
        worker_count = WorkerRegistry.get_worker_count()
        active_workers = WorkerRegistry.get_active_workers()
        workers_by_type = WorkerRegistry.get_workers_by_type()
    except Exception:
        worker_count = 0
        active_workers = []
        workers_by_type = {'web': [], 'celery': [], 'beat': [], 'discord_bot': []}

    context = {
        'page_title': 'Logging Configuration',
        'loggers_by_category': loggers_by_category,
        'log_levels': log_levels,
        'total_customized': sum(1 for c in saved_configs.values() if c.is_active),
        'worker_count': worker_count,
        'active_workers': active_workers,
        'workers_by_type': workers_by_type,
    }

    return render(request, 'djquark_workers/logging_settings.html', context)


@quark_admin_required
@require_POST
def logging_set_level(request):
    """
    API endpoint to set a single logger's level.
    Used for AJAX updates from the admin panel.
    """
    try:
        data = json.loads(request.body)
        logger_name = data.get('logger_name', '')
        level = data.get('level', 'INFO').upper()

        if level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            return JsonResponse({'success': False, 'error': 'Invalid log level'})

        # Get display name for this logger
        display_name = logger_name or 'Root Logger'
        for name, desc, cat in quark_settings.CONFIGURABLE_LOGGERS:
            if name == logger_name:
                display_name = desc
                break

        # Save to database and apply
        LoggingConfig.set_logger_level(
            logger_name=logger_name,
            level=level,
            user=request.user,
            description=display_name,
        )

        # Apply to all workers
        LoggingManager.set_level(logger_name, level, broadcast=True)

        return JsonResponse({
            'success': True,
            'logger_name': logger_name or '(root)',
            'level': level,
            'message': f"Logger '{logger_name or 'root'}' set to {level}"
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    except Exception as e:
        logger.exception(f"Error setting log level: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@quark_admin_required
@require_POST
def logging_reset_all(request):
    """
    API endpoint to reset all loggers to defaults.
    """
    try:
        count = LoggingConfig.reset_all()
        LoggingManager.reset_to_defaults()

        return JsonResponse({
            'success': True,
            'message': f'Reset {count} custom logging level(s) to defaults',
            'count': count
        })

    except Exception as e:
        logger.exception(f"Error resetting logging config: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@quark_admin_required
def worker_status(request):
    """
    Display current worker status.
    """
    try:
        worker_count = WorkerRegistry.get_worker_count()
        active_workers = WorkerRegistry.get_active_workers()
        workers_by_type = WorkerRegistry.get_workers_by_type()

        # Get detailed info for each worker
        workers_info = []
        for worker_id in active_workers:
            info = WorkerRegistry.get_worker_info(worker_id)
            if info:
                info['worker_id'] = worker_id
                workers_info.append(info)
    except Exception as e:
        logger.exception(f"Error getting worker status: {e}")
        worker_count = 0
        active_workers = []
        workers_by_type = {}
        workers_info = []

    context = {
        'page_title': 'Worker Status',
        'worker_count': worker_count,
        'active_workers': active_workers,
        'workers_by_type': workers_by_type,
        'workers_info': workers_info,
    }

    return render(request, 'djquark_workers/worker_status.html', context)


@quark_admin_required
def worker_status_api(request):
    """
    API endpoint for worker status (JSON).
    """
    try:
        worker_count = WorkerRegistry.get_worker_count()
        active_workers = WorkerRegistry.get_active_workers()
        workers_by_type = WorkerRegistry.get_workers_by_type()

        workers_info = []
        for worker_id in active_workers:
            info = WorkerRegistry.get_worker_info(worker_id)
            if info:
                info['worker_id'] = worker_id
                workers_info.append(info)

        return JsonResponse({
            'success': True,
            'worker_count': worker_count,
            'active_workers': active_workers,
            'workers_by_type': workers_by_type,
            'workers_info': workers_info,
        })

    except Exception as e:
        logger.exception(f"Error getting worker status: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

