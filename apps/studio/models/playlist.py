from django.db import models

from config.model import BaseModel

from .base import Studio


class Playlist(BaseModel):
    studio = models.ForeignKey(
        "studio.Studio", on_delete=models.CASCADE, related_name="playlists"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_rotation = models.BooleanField(default=False)

    avoid_recent_minutes = models.PositiveIntegerField(default=30)
    max_daily_spins = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "playlists"
        unique_together = ("studio", "name")

    def __str__(self):
        return self.name


class PlaylistItem(BaseModel):
    playlist = models.ForeignKey(
        Playlist, on_delete=models.CASCADE, related_name="items"
    )
    track = models.ForeignKey(
        "medias.Track", on_delete=models.CASCADE, null=True, related_name="playlist_items"
    )

    position = models.PositiveIntegerField()
    weight = models.FloatField(default=1.0)
    start_offset_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "playlist_items"
        unique_together = ("playlist", "position")
        ordering = ["position"]
        indexes = [
            models.Index(fields=["playlist", "position"]),
            models.Index(fields=["track"]),
        ]


class RotationRule(BaseModel):
    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="rotation_rules"
    )
    name = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True)
    rule_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "rotation_rules"
        unique_together = ("studio", "name")
