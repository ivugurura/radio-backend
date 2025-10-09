
from django.db import models

from config.model import BaseModel


class Track(BaseModel):
    class State(models.TextChoices):
        UPLOADING = "UPLOADING"
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        READY = "READY"
        FAILED = "FAILED"
        ARCHIVED = "ARCHIVED"

    studio = models.ForeignKey("apps.studio.Studio", on_delete=models.CASCADE, related_name="tracks")

    title = models.CharField(max_length=255, blank=True)
    artist = models.CharField(max_length=255, blank=True)
    album = models.CharField(max_length=255, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    genre = models.CharField(max_length=128, blank=True)

    state = models.CharField(max_length=16, choices=State.choices, default=State.UPLOADING)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    bitrate_kbps = models.PositiveIntegerField(null=True, blank=True)
    loudness_lufs = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    peak_dbfs = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    content_hash = models.CharField(max_length=64, db_index=True)
    is_duplicate_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates")

    processed_storage_key = models.CharField(max_length=512, blank=True)
    upload_session = models.ForeignKey("apps.media.UploadSession", null=True, blank=True, on_delete=models.SET_NULL, related_name="tracks")

    is_active = models.BooleanField(default=True)
    is_explicit = models.BooleanField(default=False)

    class Meta:
        db_table = "tracks"
        unique_together = ("studio", "content_hash")
        indexes = [
            models.Index(fields=["studio", "state"]),
            models.Index(fields=["studio", "is_active", "state"]),
        ]

    def __str__(self):
        return self.title or self.id.hex

class TrackAsset(BaseModel):
    class AssetType(models.TextChoices):
        RAW_ORIGINAL = "RAW_ORIGINAL"
        NORMALIZED_MP3 = "NORMALIZED_MP3"
        WAVEFORM_JSON = "WAVEFORM_JSON"
        COVER_ART = "COVER_ART"
        ALT_ENCODING = "ALT_ENCODING"

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="assets")
    asset_type = models.CharField(max_length=32, choices=AssetType.choices)
    storage_key = models.CharField(max_length=512)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=64, blank=True)
    checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "track_assets"
        unique_together = ("track", "asset_type", "storage_key")
        indexes = [models.Index(fields=["track", "asset_type"])]