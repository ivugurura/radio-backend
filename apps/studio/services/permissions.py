"""Studio-scoped permissions.

Every staff action belongs to a studio. A user may act on a studio only through
their ``StudioMembership`` role there; ``ROLE_PERMS`` maps each role to what it
allows. Superusers (platform admins) pass every check. ``is_staff`` only grants
Django admin access and gives no studio rights.
"""

from enum import StrEnum
from functools import wraps

from graphql_jwt.decorators import login_required

from apps.common.translations import translate
from apps.studio.models.base import Studio, StudioMembership
from apps.studio.services.helpers import get_studio

Role = StudioMembership.Role


class Perm(StrEnum):
    VIEW_ANALYTICS = 'VIEW_ANALYTICS'
    VIEW_MEDIA = 'VIEW_MEDIA'
    MANAGE_MEDIA = 'MANAGE_MEDIA'
    CONTROL_PLAYBACK = 'CONTROL_PLAYBACK'
    MODERATE_CHAT = 'MODERATE_CHAT'
    VIEW_STREAM_CREDS = 'VIEW_STREAM_CREDS'
    ROTATE_STREAM_CREDS = 'ROTATE_STREAM_CREDS'
    EDIT_SETTINGS = 'EDIT_SETTINGS'
    MANAGE_MEMBERS = 'MANAGE_MEMBERS'


ALL_PERMS = frozenset(Perm)

ROLE_PERMS: dict[str, frozenset[Perm]] = {
    Role.OWNER: ALL_PERMS,
    Role.ADMIN: ALL_PERMS,
    Role.EDITOR: frozenset({Perm.VIEW_ANALYTICS, Perm.VIEW_MEDIA, Perm.MANAGE_MEDIA}),
    # DJs go live, so they need the encoder credentials, but not to rotate them.
    Role.DJ: frozenset(
        {
            Perm.VIEW_ANALYTICS,
            Perm.VIEW_MEDIA,
            Perm.CONTROL_PLAYBACK,
            Perm.MODERATE_CHAT,
            Perm.VIEW_STREAM_CREDS,
        }
    ),
    Role.ANALYST: frozenset({Perm.VIEW_ANALYTICS}),
    Role.VIEWER: frozenset({Perm.VIEW_ANALYTICS, Perm.VIEW_MEDIA}),
}

# Higher rank outranks lower. Used to limit who may grant or revoke which role.
ROLE_RANK: dict[str, int] = {
    Role.OWNER: 50,
    Role.ADMIN: 40,
    Role.EDITOR: 30,
    Role.DJ: 20,
    Role.ANALYST: 10,
    Role.VIEWER: 0,
}

# Roles are cached on the user object, which lives for one request (or one
# websocket connection), so a resolver tree costs one query per studio.
_ROLE_CACHE_ATTR = '_studio_role_cache'


def _is_authenticated(user) -> bool:
    return bool(user) and getattr(user, 'is_authenticated', False)


def is_platform_admin(user) -> bool:
    return _is_authenticated(user) and bool(getattr(user, 'is_superuser', False))


def get_role(user, studio: Studio) -> str | None:
    """The user's membership role in ``studio``, or None if not a member."""
    if not _is_authenticated(user):
        return None
    cache = getattr(user, _ROLE_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(user, _ROLE_CACHE_ATTR, cache)
    if studio.pk not in cache:
        cache[studio.pk] = (
            StudioMembership.objects.filter(studio=studio, user=user)
            .values_list('role', flat=True)
            .first()
        )
    return cache[studio.pk]


def clear_role_cache(user) -> None:
    """Forget cached roles, e.g. after changing the user's memberships."""
    if user is not None and hasattr(user, _ROLE_CACHE_ATTR):
        delattr(user, _ROLE_CACHE_ATTR)


def get_permissions(user, studio: Studio) -> frozenset[Perm]:
    if is_platform_admin(user):
        return ALL_PERMS
    return ROLE_PERMS.get(get_role(user, studio), frozenset())


def has_perm(user, studio: Studio, perm: Perm) -> bool:
    return perm in get_permissions(user, studio)


def has_studio_access(user, studio: Studio) -> bool:
    return is_platform_admin(user) or get_role(user, studio) is not None


def can_assign_role(actor, studio: Studio, role: str) -> bool:
    """Whether ``actor`` may grant, change or revoke ``role`` in ``studio``.

    Owners manage every role. Other members with MANAGE_MEMBERS (admins) only
    manage roles ranked below their own.
    """
    if role not in ROLE_RANK or not has_perm(actor, studio, Perm.MANAGE_MEMBERS):
        return False
    if is_platform_admin(actor):
        return True
    actor_role = get_role(actor, studio)
    if actor_role == Role.OWNER:
        return True
    return ROLE_RANK[role] < ROLE_RANK[actor_role]


def check_perm(user, studio: Studio | None, perm: Perm | None = None) -> Studio:
    """Raise unless ``user`` may act on ``studio`` (with ``perm``, if given).

    A missing studio and a studio the user is not a member of give the same
    "not found" error, so slugs and ids can't be probed; members lacking
    ``perm`` get "forbidden". Returns the studio for chaining.
    """
    if studio is None or not has_studio_access(user, studio):
        raise Exception(translate('studio.studio_not_found'))
    if perm is not None and not has_perm(user, studio, perm):
        raise Exception(translate('common.forbidden'))
    return studio


def require_perm(perm: Perm | None, studio_arg: str = 'studio_id'):
    """GraphQL resolver/mutate decorator: requires login, resolves the studio
    from the ``studio_arg`` keyword argument and runs ``check_perm``.
    ``perm=None`` admits any member of the studio.

    The resolver receives the Studio as ``studio`` in place of ``studio_arg``.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(root, info, *args, **kwargs):
            studio = get_studio(kwargs.pop(studio_arg, '') or '')
            check_perm(info.context.user, studio, perm)
            return fn(root, info, *args, studio=studio, **kwargs)

        return login_required(wrapper)

    return decorator
