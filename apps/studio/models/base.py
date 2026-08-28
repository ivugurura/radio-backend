from django.conf import settings
from django.db import models

from config.model import BaseModel


class Studio(BaseModel):
    slug = models.SlugField(unique=True, max_length=64)
    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    default_br_kbps = models.PositiveIntegerField(default=128)
    default_sr_hz = models.PositiveIntegerField(default=48000)
    default_ch = models.PositiveIntegerField(default=2)
    auto_normalize = models.BooleanField(default=True)
    loudness_target_lufs = models.DecimalField(
        max_digits=5, decimal_places=2, default=-14.0
    )

    class Meta:
        db_table = "studios"
        indexes = [models.Index(fields=["slug"])]

    def __str__(self):
        return self.display_name


class StudioMembership(BaseModel):
    class Role(models.TextChoices):
        OWNER = "OWNER"
        ADMIN = "ADMIN"
        EDITOR = "EDITOR"
        DJ = "DJ"
        ANALYST = "ANALYST"
        VIEWER = "VIEWER"

    studio = models.ForeignKey(
        Studio, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="studio_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        db_table = "studio_memberships"
        unique_together = ("studio", "user")
        indexes = [models.Index(fields=["studio", "role"])]
