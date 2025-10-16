from django.db import models

from config.model import BaseModel

from .base import Studio
from .playlist import Playlist


class ScheduledShow(BaseModel):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name="shows")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_recurring = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="UTC")
    color_hex = models.CharField(max_length=7, blank=True)

    class Meta:
        db_table = "scheduled_shows"
        indexes = [models.Index(fields=["studio", "title"])]


class ShowSlot(BaseModel):
    class Mode(models.TextChoices):
        PLAYLIST = "PLAYLIST"
        LIVE_REQUIRED = "LIVE_REQUIRED"
        ROTATION = "ROTATION"
        SILENCE = "SILENCE"

    show = models.ForeignKey(
        ScheduledShow, on_delete=models.CASCADE, related_name="slots"
    )
    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="show_slots"
    )
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.PLAYLIST)
    playlist = models.ForeignKey(
        Playlist,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="show_slots",
    )

    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    recurrence_rule = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "show_slots"
        indexes = [
            models.Index(fields=["studio", "starts_at"]),
            models.Index(fields=["show", "starts_at"]),
        ]
