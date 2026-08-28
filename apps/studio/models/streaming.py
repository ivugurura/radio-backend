from django.db import models

from config.model import BaseModel

from .base import Studio


class StreamingCredential(BaseModel):
    """Icecast SOURCE credentials a live encoder (e.g. BUTT) authenticates with."""

    studio = models.OneToOneField(
        Studio, on_delete=models.CASCADE, related_name="streaming_credential"
    )
    username = models.CharField(max_length=64)
    password_encrypted = models.CharField(max_length=255)
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "streaming_credentials"

    def set_password(self, raw_password: str) -> None:
        from apps.studio.services.encryption import encrypt_secret

        self.password_encrypted = encrypt_secret(raw_password)

    def get_password(self) -> str:
        from apps.studio.services.encryption import decrypt_secret

        return decrypt_secret(self.password_encrypted)

    def __str__(self):
        return f"StreamingCredential({self.studio.slug})"
