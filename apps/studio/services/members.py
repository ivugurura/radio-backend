"""Managing who belongs to a studio and with which role.

Rules, on top of MANAGE_MEMBERS:
- an actor only touches roles ``can_assign_role`` allows: both the member's
  current role and the role being given (admins can't touch admins/owners);
- nobody changes or removes their own membership;
- a studio's last owner can't be demoted or removed.

Errors are raised as translated ``Exception``s, like the rest of the schema.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.translations import translate
from apps.studio.models.base import Studio, StudioMembership
from apps.studio.services.permissions import (
    ROLE_RANK,
    Perm,
    can_assign_role,
    check_perm,
)
from apps.users.models import User

Role = StudioMembership.Role


def _fail(key: str, **kwargs):
    raise Exception(translate(f'studio.{key}', **kwargs))


def _normalize_role(role) -> str:
    """GraphQL enum args may arrive as the enum member or its value."""
    value = getattr(role, 'value', role)
    if value not in Role.values:
        _fail('role_not_allowed')
    return value


def list_members(actor, studio: Studio) -> list[StudioMembership]:
    check_perm(actor, studio, Perm.MANAGE_MEMBERS)
    members = StudioMembership.objects.filter(studio=studio).select_related('user')
    return sorted(
        members,
        key=lambda m: (
            -ROLE_RANK.get(m.role, 0),
            m.user.first_name.lower(),
            m.user.last_name.lower(),
        ),
    )


def can_manage_member(actor, membership: StudioMembership) -> bool:
    """Whether ``actor`` may change or remove ``membership``."""
    if membership.user_id == getattr(actor, 'pk', None):
        return False
    return can_assign_role(actor, membership.studio, membership.role)


def _locked_membership(studio: Studio, user_id) -> StudioMembership:
    membership = (
        StudioMembership.objects.select_for_update()
        .select_related('user', 'studio')
        .filter(studio=studio, user_id=user_id)
        .first()
    )
    if membership is None:
        _fail('member_not_found')
    return membership


def _check_can_manage(actor, membership: StudioMembership) -> None:
    if membership.user_id == actor.pk:
        _fail('cannot_change_own_membership')
    if not can_assign_role(actor, membership.studio, membership.role):
        _fail('role_not_allowed')


def _ensure_other_owner(studio: Studio, membership: StudioMembership) -> None:
    """Refuse to take away the studio's last owner. Owner rows are locked so two
    concurrent demotions can't both pass."""
    if membership.role != Role.OWNER:
        return
    owners = list(
        StudioMembership.objects.select_for_update()
        .filter(studio=studio, role=Role.OWNER)
        .values_list('pk', flat=True)
    )
    if len(owners) <= 1:
        _fail('last_owner')


@transaction.atomic
def add_member(actor, studio: Studio, email: str, role) -> StudioMembership:
    check_perm(actor, studio, Perm.MANAGE_MEMBERS)
    role = _normalize_role(role)
    if not can_assign_role(actor, studio, role):
        _fail('role_not_allowed')

    user = User.objects.filter(
        email__iexact=(email or '').strip(), is_active=True
    ).first()
    if user is None:
        _fail('member_user_not_found')
    if StudioMembership.objects.filter(studio=studio, user=user).exists():
        _fail('member_exists')
    try:
        with transaction.atomic():
            return StudioMembership.objects.create(studio=studio, user=user, role=role)
    except IntegrityError:
        _fail('member_exists')


@transaction.atomic
def update_member_role(actor, studio: Studio, user_id, role) -> StudioMembership:
    check_perm(actor, studio, Perm.MANAGE_MEMBERS)
    role = _normalize_role(role)
    membership = _locked_membership(studio, user_id)
    _check_can_manage(actor, membership)
    if not can_assign_role(actor, studio, role):
        _fail('role_not_allowed')
    if membership.role == role:
        return membership
    if role != Role.OWNER:
        _ensure_other_owner(studio, membership)

    membership.role = role
    membership.updated_at = timezone.now()  # BaseModel has no auto_now
    membership.save(update_fields=['role', 'updated_at'])
    return membership


@transaction.atomic
def remove_member(actor, studio: Studio, user_id) -> None:
    check_perm(actor, studio, Perm.MANAGE_MEMBERS)
    membership = _locked_membership(studio, user_id)
    _check_can_manage(actor, membership)
    _ensure_other_owner(studio, membership)
    membership.delete()  # soft delete; the user can be added back later
