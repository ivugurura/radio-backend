import secrets
import uuid

from django.conf import settings
from django.http import HttpRequest

from apps.studio.models.base import Studio, StudioMembership
from apps.studio.models.streaming import StreamingCredential

# Slugs used before studios were renamed to language codes (migration 0009).
# Kept so old player links and encoders still resolve; remove once nothing
# requests them.
LEGACY_STUDIO_SLUGS = {
    "reformation-rw": "rw",
}


def get_studio(studio_id: str) -> Studio | None:
    """Return a Studio matched by slug, legacy slug, or pk; None if not found."""
    slug = LEGACY_STUDIO_SLUGS.get(studio_id, studio_id)
    studio = Studio.objects.filter(slug=slug).first()
    if studio:
        return studio

    try:
        pk = uuid.UUID(str(studio_id))
    except ValueError:
        return None
    return Studio.objects.filter(pk=pk).first()


def is_studio_server_request(request: HttpRequest) -> bool:
    """True when the request carries radio-studio's `Bearer <STUDIO_TOKEN>`."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    expected = getattr(settings, "STUDIO_TOKEN", "")
    if not expected or not header.startswith("Bearer "):
        return False
    return secrets.compare_digest(header[len("Bearer ") :], expected)


def can_manage_studio_settings(user, studio: Studio) -> bool:
    """OWNER/ADMIN studio members (or Django staff) may edit studio settings."""
    return can_manage_streaming_credential(user, studio)


def can_manage_streaming_credential(user, studio: Studio) -> bool:
    """OWNER/ADMIN studio members (or Django staff) may view/rotate stream credentials."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    return StudioMembership.objects.filter(
        studio=studio,
        user=user,
        role__in=[StudioMembership.Role.OWNER, StudioMembership.Role.ADMIN],
    ).exists()


def can_control_playback(user, studio: Studio) -> bool:
    """Playback control (e.g. skipping AutoDJ tracks) is limited to the same
    OWNER/ADMIN members who manage the studio's stream."""
    return can_manage_streaming_credential(user, studio)


def _generate_username(studio: Studio) -> str:
    return studio.slug


def _generate_password() -> str:
    return secrets.token_urlsafe(18)


def get_or_create_streaming_credential(studio: Studio) -> StreamingCredential:
    """Return the studio's StreamingCredential, provisioning one on first use."""
    credential = getattr(studio, "streaming_credential", None)
    if credential:
        return credential
    credential = StreamingCredential(studio=studio, username=_generate_username(studio))
    credential.set_password(_generate_password())
    credential.save()
    return credential


def regenerate_streaming_credential(studio: Studio) -> StreamingCredential:
    from django.utils import timezone

    credential = get_or_create_streaming_credential(studio)
    credential.set_password(_generate_password())
    credential.rotated_at = timezone.now()
    credential.save(update_fields=["password_encrypted", "rotated_at", "updated_at"])
    return credential
