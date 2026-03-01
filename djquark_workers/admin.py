"""
Django admin registration for djquark-workers models.
"""

from django.contrib import admin
from .models import LoggingConfig


@admin.register(LoggingConfig)
class LoggingConfigAdmin(admin.ModelAdmin):
    """Admin interface for LoggingConfig model."""

    list_display = ['logger_name_display', 'level', 'is_active', 'updated_at', 'updated_by']
    list_filter = ['level', 'is_active']
    search_fields = ['logger_name', 'description']
    readonly_fields = ['updated_at', 'updated_by']
    ordering = ['logger_name']

    fieldsets = (
        (None, {
            'fields': ('logger_name', 'level', 'description', 'is_active')
        }),
        ('Audit Info', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def logger_name_display(self, obj):
        """Display logger name with special handling for root logger."""
        return obj.logger_name or '(root)'
    logger_name_display.short_description = 'Logger Name'
    logger_name_display.admin_order_field = 'logger_name'

    def save_model(self, request, obj, form, change):
        """Auto-set the updated_by field."""
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

