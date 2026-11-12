"""Creating, listing and (de)activating studios. Platform admins only.

A studio's slug is the language it serves, so it must be a supported language
code no other studio holds. The slug can't change after creation: it names the
media folder, the encoder mount and the studio in radio-studio and the UI.

Deactivating is the only removal. Tracks, analytics and chat history point at
the studio, so it is never deleted from here, and it can be reactivated.
"""

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.common.translations import SUPPORTED_LANGUAGES, translate
from apps.studio.models.base import Studio, StudioMembership
from apps.studio.services.helpers import (
    LEGACY_STUDIO_SLUGS,
    get_or_create_streaming_credential,
    get_studio,
)
from apps.studio.services.permissions import clear_role_cache, is_platform_admin
from apps.studio.services.studio_control import request_studio_sync

DISPLAY_NAME_MAX = 120


def _fail(key: str, **kwargs):
    raise Exception(translate(key, **kwargs))


def require_platform_admin(actor) -> None:
    if not is_platform_admin(actor):
        _fail('common.forbidden')


def _taken_slugs() -> set[str]:
    # The slug column is unique across soft-deleted rows too.
    return set(Studio.all_objects.values_list('slug', flat=True))


def available_slugs(actor) -> list[str]:
    """Language codes a new studio may still use."""
    require_platform_admin(actor)
    taken = _taken_slugs()
    return [code for code in SUPPORTED_LANGUAGES if code not in taken]


def list_studios(actor, include_inactive: bool = True) -> QuerySet:
    require_platform_admin(actor)
    studios = Studio.objects.annotate(
        member_count=Count(
            'memberships',
            filter=Q(memberships__deleted_at__isnull=True),
            distinct=True,
        ),
        track_count=Count(
            'tracks', filter=Q(tracks__deleted_at__isnull=True), distinct=True
        ),
    ).select_related('streaming_credential')
    if not include_inactive:
        studios = studios.filter(is_active=True)
    return studios.order_by('slug')


def get_managed_studio(actor, studio_id: str) -> Studio:
    require_platform_admin(actor)
    studio = get_studio(studio_id or '')
    if studio is None:
        _fail('studio.studio_not_found')
    return studio


def _clean_slug(slug: str) -> str:
    slug = (slug or '').strip().lower()
    if slug not in SUPPORTED_LANGUAGES or slug in LEGACY_STUDIO_SLUGS:
        _fail('studio.invalid_slug', choices=', '.join(SUPPORTED_LANGUAGES))
    return slug


def _clean_display_name(display_name: str) -> str:
    display_name = (display_name or '').strip()
    if not display_name or len(display_name) > DISPLAY_NAME_MAX:
        _fail('studio.invalid_display_name', max=DISPLAY_NAME_MAX)
    return display_name


def _owner(owner_user_id):
    from apps.users.models import User

    user = User.objects.filter(pk=owner_user_id).first()
    if user is None:
        _fail('auth.user_not_found')
    if not user.is_active:
        _fail('auth.user_disabled')
    return user


def _notify_radio_studio() -> None:
    """After commit, ask radio-studio to re-check the active studios so the
    change takes effect now rather than at its next poll. It reads the list
    back from us, so it must not run before the change is committed."""
    transaction.on_commit(request_studio_sync, robust=True)


def _create_media_folders(studio: Studio) -> None:
    # studio_paths() creates the folder tree as a side effect.
    from apps.medias.services.paths import studio_paths

    studio_paths(studio, studio.default_br_kbps)


@transaction.atomic
def create_studio(
    actor,
    slug: str,
    display_name: str,
    description: str = '',
    owner_user_id=None,
) -> Studio:
    """Create a studio with the platform audio format, its encoder credentials
    and, optionally, an owner. Media folders are created after commit."""
    require_platform_admin(actor)
    slug = _clean_slug(slug)
    display_name = _clean_display_name(display_name)
    owner = _owner(owner_user_id) if owner_user_id else None
    if slug in _taken_slugs():
        _fail('studio.slug_taken', slug=slug)

    # The library and the live/AutoDJ splice need one audio format, so new
    # studios take the transcoder's targets rather than a per-studio choice.
    studio = Studio.objects.create(
        slug=slug,
        display_name=display_name,
        description=(description or '').strip(),
        default_br_kbps=settings.DEFAULT_TARGET_BR_KBPS,
        default_sr_hz=settings.DEFAULT_TARGET_SR_HZ,
    )
    get_or_create_streaming_credential(studio)
    if owner is not None:
        StudioMembership.objects.create(
            studio=studio, user=owner, role=StudioMembership.Role.OWNER
        )
        clear_role_cache(owner)
    transaction.on_commit(lambda: _create_media_folders(studio))
    _notify_radio_studio()
    return studio


@transaction.atomic
def set_studio_active(actor, studio_id: str, active: bool) -> Studio:
    """Deactivating hides the studio from members and from radio-studio's next
    sync. The last active studio can't be deactivated: the listener page
    falls back to it."""
    found = get_managed_studio(actor, studio_id)
    studio = Studio.objects.select_for_update().get(pk=found.pk)
    if studio.is_active == active:
        return studio
    if not active:
        # Lock every active row so two concurrent deactivations can't both pass.
        active_ids = list(
            Studio.objects.select_for_update()
            .filter(is_active=True)
            .values_list('pk', flat=True)
        )
        if len(active_ids) <= 1:
            _fail('studio.last_active_studio')

    studio.is_active = active
    studio.updated_at = timezone.now()  # BaseModel has no auto_now
    studio.save(update_fields=['is_active', 'updated_at'])
    _notify_radio_studio()
    return studio
