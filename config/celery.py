"""
Celery app configuration for the Django project.

Place this file at config/celery.py and ensure config/__init__.py imports the `celery_app`.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

celery_app = Celery("radio_api")
celery_app.config_from_object("django.conf:settings", namespace="CELERY")
celery_app.autodiscover_tasks()
