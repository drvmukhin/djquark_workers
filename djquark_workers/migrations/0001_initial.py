# Generated manually for djquark-workers package

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LoggingConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('logger_name', models.CharField(db_index=True, help_text="Logger name (e.g., 'myapp', 'uvicorn.access', '' for root)", max_length=100, unique=True)),
                ('level', models.CharField(choices=[('DEBUG', 'DEBUG - Detailed diagnostic info'), ('INFO', 'INFO - General operational info'), ('WARNING', 'WARNING - Something unexpected'), ('ERROR', 'ERROR - Serious problem'), ('CRITICAL', 'CRITICAL - Program may not continue')], default='INFO', help_text='Log level for this logger', max_length=10)),
                ('description', models.CharField(blank=True, help_text='Human-readable description of this logger', max_length=255)),
                ('is_active', models.BooleanField(default=True, help_text='Whether this custom level is active (vs using settings.py default)')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quark_logging_config_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Logging Configuration',
                'verbose_name_plural': 'Logging Configurations',
                'db_table': 'djquark_logging_config',
                'ordering': ['logger_name'],
            },
        ),
    ]

