from django.conf import settings
from django.db import models

from config.model import BaseModel

from .base import Studio


class LiveSession(BaseModel):
    class State(models.TextChoices):
        ACTIVE = "ACTIVE"
        ENDED = "ENDED"

    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="live_sessions"
    )
    state = models.CharField(max_length=8, choices=State.choices, default=State.ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="live_started_sessions",
    )

    source_ip_hash = models.CharField(max_length=64, blank=True)
    mountpoint = models.CharField(max_length=128, blank=True)
    metadata_name = models.CharField(max_length=255, blank=True)
    metadata_bitrate = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "live_sessions"
        indexes = [
            models.Index(fields=["studio", "state"]),
            models.Index(fields=["started_at"]),
        ]
