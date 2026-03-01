"""
Django models for djquark-workers.

Contains the LoggingConfig model for persisting logging configuration.
"""

from django.db import models
from django.conf import settings


class LoggingConfig(models.Model):
    """
    Persists dynamic logging configuration in database.

    Each row represents a logger that has been customized from its default level.
    Changes are applied at runtime across all worker processes via Redis pub/sub.

    Usage:
        # Get all active configs
        configs = LoggingConfig.get_all_active()

        # Set a logger level
        LoggingConfig.set_logger_level('myapp', 'DEBUG', user=request.user)
    """

    class LogLevel(models.TextChoices):
        DEBUG = 'DEBUG', 'DEBUG - Detailed diagnostic info'
        INFO = 'INFO', 'INFO - General operational info'
        WARNING = 'WARNING', 'WARNING - Something unexpected'
        ERROR = 'ERROR', 'ERROR - Serious problem'
        CRITICAL = 'CRITICAL', 'CRITICAL - Program may not continue'

    logger_name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Logger name (e.g., 'myapp', 'uvicorn.access', '' for root)"
    )
    level = models.CharField(
        max_length=10,
        choices=LogLevel.choices,
        default=LogLevel.INFO,
        help_text="Log level for this logger"
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable description of this logger"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this custom level is active (vs using settings.py default)"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quark_logging_config_updates'
    )

    class Meta:
        db_table = 'djquark_logging_config'
        verbose_name = 'Logging Configuration'
        verbose_name_plural = 'Logging Configurations'
        ordering = ['logger_name']

    def __str__(self):
        status = "●" if self.is_active else "○"
        name = self.logger_name or "(root)"
        return f"{status} {name}: {self.level}"

    @classmethod
    def get_all_active(cls) -> dict:
        """Get all active logging configurations as a dict."""
        return {
            config.logger_name: config.level
            for config in cls.objects.filter(is_active=True)
        }

    @classmethod
    def set_logger_level(cls, logger_name: str, level: str, user=None,
                         description: str = '') -> 'LoggingConfig':
        """
        Set a logger's level in the database.

        Args:
            logger_name: The logger name (e.g., 'myapp', 'uvicorn.access')
            level: The log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            user: The user making the change
            description: Optional description for this logger

        Returns:
            The LoggingConfig instance
        """
        defaults = {
            'level': level.upper(),
            'updated_by': user,
            'is_active': True,
        }

        if description:
            defaults['description'] = description

        config, created = cls.objects.update_or_create(
            logger_name=logger_name,
            defaults=defaults
        )

        return config

    @classmethod
    def reset_logger(cls, logger_name: str) -> None:
        """Deactivate a logger's custom config (reverts to settings.py default)."""
        cls.objects.filter(logger_name=logger_name).update(is_active=False)

    @classmethod
    def reset_all(cls) -> int:
        """Deactivate all custom configs. Returns count of deactivated configs."""
        return cls.objects.filter(is_active=True).update(is_active=False)

