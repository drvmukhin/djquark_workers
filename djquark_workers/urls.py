"""
URL patterns for djquark-workers admin panel.

Include these URLs in your project's urls.py:

    path('admin/workers/', include('djquark_workers.urls')),
"""

from django.urls import path
from . import views

app_name = 'djquark_workers'

urlpatterns = [
    # Logging Configuration
    path('logging/', views.logging_settings, name='logging_settings'),
    path('logging/set-level/', views.logging_set_level, name='logging_set_level'),
    path('logging/reset/', views.logging_reset_all, name='logging_reset_all'),

    # Worker Status
    path('status/', views.worker_status, name='worker_status'),
    path('status/api/', views.worker_status_api, name='worker_status_api'),
]

