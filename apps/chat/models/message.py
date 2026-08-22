from django.conf import settings
from django.db import models

from config.model import BaseModel


class ChatMessage(BaseModel):
    class AuthorType(models.TextChoices):
        ADMIN = "ADMIN"
        LISTENER = "LISTENER"

    studio = models.ForeignKey(
        "studio.Studio", on_delete=models.CASCADE, related_name="chat_messages"
    )
    author_type = models.CharField(max_length=8, choices=AuthorType.choices)

    # Set only for ADMIN messages
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chat_messages",
    )

    # Set only for LISTENER messages
    listener_client_id = models.CharField(max_length=64, blank=True, db_index=True)
    listener_display_name = models.CharField(max_length=80, blank=True)

    body = models.TextField()

    # Only ever populated for admin-authored messages; enforced in the consumer.
    quoted_message = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quoted_by",
    )

    class Meta:
        db_table = "chat_messages"
        indexes = [
            models.Index(fields=["studio", "created_at"]),
            models.Index(fields=["studio", "listener_client_id"]),
        ]
