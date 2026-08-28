import secrets

from apps.studio.models.base import Studio, StudioMembership
from apps.studio.models.streaming import StreamingCredential


def get_studio(studio_id: str) -> Studio | None:
    """Return a Studio matched by slug, pk, or code; None if not found.

    Lookup order:
    1. slug field
    2. primary key (pk)
    3. code field
    All exceptions are swallowed; only Studio.DoesNotExist/ValueError expected.
    """
    # Try slug first (never raises)
    studio = Studio.objects.filter(slug=studio_id).first()
    if studio:
        return studio

    # Try primary key (may raise DoesNotExist or ValueError if invalid type)
    try:
        studio = Studio.objects.get(pk=studio_id)
        return studio
    except (Studio.DoesNotExist, ValueError):
        pass

    # Finally try code
    studio = Studio.objects.filter(code=studio_id).first()
    return studio


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
