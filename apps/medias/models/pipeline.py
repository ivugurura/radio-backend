from django.db import models

from config.model import BaseModel


class TranscodeJob(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED"
        RUNNING = "RUNNING"
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"
        CANCELED = "CANCELED"

    studio = models.ForeignKey(
        "studio.Studio", on_delete=models.CASCADE, related_name="transcode_jobs"
    )
    track = models.ForeignKey(
        "medias.Track", on_delete=models.CASCADE, related_name="transcode_jobs"
    )
    upload_session = models.ForeignKey(
        "medias.UploadSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transcode_jobs",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.QUEUED
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=64, blank=True)
    attempt = models.PositiveIntegerField(default=1)
    error_message = models.TextField(blank=True)

    input_storage_key = models.CharField(max_length=512, blank=True)
    output_storage_key = models.CharField(max_length=512, blank=True)

    loudness_lufs = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    peak_dbfs = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    target_bitrate_kbps = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "transcode_jobs"
        indexes = [
            models.Index(fields=["studio", "status"]),
            models.Index(fields=["track", "status"]),
        ]
