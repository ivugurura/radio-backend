# Ensure that the Celery app is imported whenever Django starts so workers and management commands pick it up.
from .celery import celery_app  # noqa: F401

__all__ = ("celery_app",)
