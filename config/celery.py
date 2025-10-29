"""
Celery app configuration for the Django project.

Place this file at config/celery.py and ensure config/__init__.py imports the `celery_app`.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

celery_app = Celery("radio_backend")
# read configuration from Django settings with prefix CELERY_
celery_app.config_from_object("django.conf:settings", namespace="CELERY")
# auto-discover tasks.py in installed apps
celery_app.autodiscover_tasks()
