"""URL configuration for tests."""

from django.urls import path, include

urlpatterns = [
    path('workers/', include('djquark_workers.urls')),
]

