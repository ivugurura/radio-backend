from django.db import models

from config.model import BaseModel

from .base import Studio


class PlayEvent(BaseModel):
    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="play_events"
    )
    track = models.ForeignKey(
        "media.Track", on_delete=models.SET_NULL, null=True, related_name="play_events"
    )

    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=16, default="AUTO")  # AUTO/LIVE/MANUAL
    sequence = models.BigIntegerField()

    class Meta:
        db_table = "play_events"
        unique_together = ("studio", "sequence")
        indexes = [
            models.Index(fields=["studio", "started_at"]),
            models.Index(fields=["studio", "sequence"]),
        ]


class ListenerSession(BaseModel):
    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="listener_sessions"
    )

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)

    ip_hash = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    client_type = models.CharField(max_length=32, blank=True)

    country = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=64, blank=True)
    city = models.CharField(max_length=128, blank=True)
    lat = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    lon = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)

    total_bytes = models.BigIntegerField(default=0)

    class Meta:
        db_table = "listener_sessions"
        indexes = [
            models.Index(fields=["studio", "started_at"]),
            models.Index(fields=["studio", "ended_at"]),
            models.Index(fields=["studio", "country"]),
        ]


class ListenerStatBucket(BaseModel):
    INTERVAL_CHOICES = (
        ("MINUTE", "Minute"),
        ("FIVE_MIN", "Five Minutes"),
        ("HOUR", "Hour"),
    )
    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="listener_buckets"
    )
    interval = models.CharField(
        max_length=16, choices=INTERVAL_CHOICES, default="MINUTE"
    )
    bucket_start = models.DateTimeField(db_index=True)

    active_peak = models.PositiveIntegerField()
    listener_minutes = models.PositiveIntegerField()
    countries_json = models.JSONField(default=dict)

    class Meta:
        db_table = "listener_stat_buckets"
        unique_together = ("studio", "interval", "bucket_start")
        indexes = [models.Index(fields=["studio", "interval", "bucket_start"])]
