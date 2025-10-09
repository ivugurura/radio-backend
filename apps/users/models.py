import uuid
from django.conf import settings
from django.db import models

from config.model import BaseModel


class UserProfile(BaseModel):
    """
    Optional extension profile. Keep minimal until needed.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=120, blank=True)
    avatar_url = models.URLField(blank=True)
    timezone = models.CharField(max_length=64, default="UTC")

    def __str__(self):
        return self.display_name or self.user.get_username()