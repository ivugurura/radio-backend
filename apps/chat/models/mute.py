from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from config.model import BaseModel


class ChatMute(BaseModel):
    studio = models.ForeignKey(
        "studio.Studio", on_delete=models.CASCADE, related_name="chat_mutes"
    )
    listener_client_id = models.CharField(max_length=64, db_index=True)

    muted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chat_mutes_issued",
    )
    reason = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # null = permanent ban

    class Meta:
        db_table = "chat_mutes"
        indexes = [
            models.Index(fields=["studio", "listener_client_id"]),
        ]


def is_listener_muted(studio, listener_client_id: str) -> bool:
    """True if the listener has an active mute (objects already excludes unmuted/soft-deleted rows)."""
    return (
        ChatMute.objects.filter(studio=studio, listener_client_id=listener_client_id)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .exists()
    )
