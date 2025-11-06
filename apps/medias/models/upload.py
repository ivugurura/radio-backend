from django.db import models

from config.model import BaseModel


class UploadSession(BaseModel):
    class Source(models.TextChoices):
        DIRECT = "DIRECT"
        ADMIN_PANEL = "ADMIN_PANEL"
        API = "API"

    studio = models.ForeignKey(
        "studio.Studio", on_delete=models.CASCADE, related_name="upload_sessions"
    )
    original_filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=64, blank=True)
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.DIRECT
    )
    storage_incoming_key = models.CharField(max_length=512, blank=True)
    # Upload lifecycle
    finalized = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    # Local disk upload state
    temp_rel_path = models.CharField(max_length=512, blank=True)
    bytes_received = models.BigIntegerField(default=0)

    # Upload authorization (for PUT chunks)
    upload_token = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"{self.original_filename} ({self.id})"

    class Meta:
        db_table = "upload_sessions"
