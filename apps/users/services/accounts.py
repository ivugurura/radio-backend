"""Account lifecycle: invites, password resets, and platform user management.

Who may do what:
- superusers manage every account (list, edit, disable, reset, sign out) and
  may invite without a studio;
- studio members with MANAGE_MEMBERS invite people into their own studio, for
  roles ``can_assign_role`` allows. Inviting an existing account just adds the
  membership; no link is issued for an account that already has a password.

One-time links (``AccountToken``) are stored hashed. Issuing a new link of a
purpose retires the user's older unused ones, so only the latest link works.
"""

import datetime
import hashlib
import re
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from graphql_jwt.refresh_token.utils import get_refresh_token_model
from rest_framework.authtoken.models import Token

from apps.common.translations import translate
from apps.studio.models.base import Studio, StudioMembership
from apps.studio.services.permissions import (
    Perm,
    can_assign_role,
    check_perm,
    is_platform_admin,
)
from apps.users.models import AccountToken, User
from apps.users.tasks import send_account_email

Purpose = AccountToken.Purpose

LINK_PATHS = {
    Purpose.INVITE: '/accept-invite',
    Purpose.PASSWORD_RESET: '/reset-password',
}
# A user can ask for a reset email at most this often.
RESET_REQUEST_COOLDOWN = datetime.timedelta(seconds=60)


def _fail(key: str, **kwargs):
    raise Exception(translate(key, **kwargs))


def require_superuser(actor) -> None:
    if not is_platform_admin(actor):
        _fail('common.forbidden')


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _ttl(purpose: str) -> datetime.timedelta:
    if purpose == Purpose.INVITE:
        return datetime.timedelta(hours=settings.INVITE_TOKEN_TTL_HOURS)
    return datetime.timedelta(minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES)


def _retire_tokens(user: User, purpose: str | None = None) -> None:
    tokens = AccountToken.objects.filter(user=user, used_at__isnull=True)
    if purpose:
        tokens = tokens.filter(purpose=purpose)
    tokens.update(used_at=timezone.now())


def issue_link(user: User, purpose: str, created_by=None) -> str:
    """Create a one-time link for ``user``, retiring older unused ones."""
    _retire_tokens(user, purpose)
    raw = secrets.token_urlsafe(32)
    AccountToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=_hash(raw),
        created_by=created_by if getattr(created_by, 'pk', None) else None,
        expires_at=timezone.now() + _ttl(purpose),
    )
    return f'{settings.FRONTEND_URL}{LINK_PATHS[purpose]}?token={raw}'


def queue_email(user: User, purpose: str, link: str, **context) -> bool:
    """Send the link by email after the transaction commits. Returns whether
    an email will go out (False when SMTP isn't configured)."""
    if not settings.EMAIL_ENABLED:
        return False
    key = 'invite' if purpose == Purpose.INVITE else 'reset'
    app = translate('auth.email_app_name')
    params = {
        'name': user.first_name or user.email,
        'link': link,
        'app': app,
        'inviter': app,
        'studio': app,
        **context,
    }
    if purpose == Purpose.INVITE:
        params['days'] = max(1, settings.INVITE_TOKEN_TTL_HOURS // 24)
    else:
        params['minutes'] = settings.PASSWORD_RESET_TOKEN_TTL_MINUTES
    subject = translate(f'auth.email_{key}_subject', **params)
    body = translate(f'auth.email_{key}_body', **params)
    to = user.email
    transaction.on_commit(lambda: send_account_email.delay(to, subject, body))
    return True


def find_token(raw: str, purpose: str | None = None) -> AccountToken | None:
    """The usable token matching ``raw`` (unused, unexpired, active user)."""
    if not raw:
        return None
    token = (
        AccountToken.objects.select_related('user')
        .filter(token_hash=_hash(raw))
        .first()
    )
    if token is None or not token.is_usable or not token.user.is_active:
        return None
    if purpose and token.purpose != purpose:
        return None
    return token


def revoke_sessions(user: User) -> None:
    """Sign the user out everywhere: refresh tokens and the REST token go.
    Access tokens are stateless and lapse within JWT_EXPIRATION_DELTA."""
    get_refresh_token_model().objects.filter(user=user, revoked__isnull=True).update(
        revoked=timezone.now()
    )
    Token.objects.filter(user=user).delete()


def _set_password(user: User, password: str) -> None:
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise Exception(' '.join(exc.messages))
    user.set_password(password)


def _clean_email(email: str) -> str:
    email = User.objects.normalize_email((email or '').strip()).lower()
    try:
        validate_email(email)
    except ValidationError:
        _fail('auth.invalid_email')
    return email


def _display_name(user) -> str:
    return ' '.join(filter(None, [user.first_name, user.last_name])) or user.email


def _unique_user_name(email: str) -> str:
    base = re.sub(r'[^a-z0-9._-]', '', email.split('@')[0].lower())[:40] or 'user'
    candidate, n = base, 1
    while User.objects.filter(user_name__iexact=candidate).exists():
        n += 1
        candidate = f'{base}{n}'
    return candidate


# --------------------------------------------------------------------- invites


@dataclass
class InviteResult:
    user: User
    created: bool
    link: str | None
    emailed: bool


@transaction.atomic
def invite_user(
    actor,
    email: str,
    first_name: str = '',
    last_name: str = '',
    studio: Studio | None = None,
    role: str | None = None,
) -> InviteResult:
    if studio is None:
        require_superuser(actor)
    else:
        check_perm(actor, studio, Perm.MANAGE_MEMBERS)
        if not role or not can_assign_role(actor, studio, role):
            _fail('studio.role_not_allowed')

    email = _clean_email(email)
    user = User.objects.select_for_update().filter(email__iexact=email).first()
    created = user is None
    if user is not None and not user.is_active:
        _fail('auth.user_disabled')

    if created:
        first_name, last_name = (first_name or '').strip(), (last_name or '').strip()
        if not first_name or not last_name:
            _fail('auth.name_required')
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            user_name=_unique_user_name(email),
            is_verified=False,
        )
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            _fail('auth.email_taken')

    if studio is not None:
        membership_exists = StudioMembership.objects.filter(
            studio=studio, user=user
        ).exists()
        if membership_exists and not user.is_pending:
            _fail('studio.member_exists')
        if not membership_exists:
            StudioMembership.objects.create(studio=studio, user=user, role=role)

    if not user.is_pending:
        # An account with a password: the membership is all that changes.
        return InviteResult(user=user, created=False, link=None, emailed=False)

    link = issue_link(user, Purpose.INVITE, created_by=actor)
    context = {'inviter': _display_name(actor)}
    if studio is not None:
        context['studio'] = studio.display_name
    emailed = queue_email(user, Purpose.INVITE, link, **context)
    return InviteResult(user=user, created=created, link=link, emailed=emailed)


@transaction.atomic
def accept_invite(raw: str, password: str) -> User:
    token = find_token(raw, Purpose.INVITE)
    if token is None:
        _fail('auth.link_invalid')
    user = token.user
    _set_password(user, password)
    user.is_verified = True
    user.save(update_fields=['password', 'is_verified', 'updated_at'])
    _retire_tokens(user)
    return user


# ------------------------------------------------------------ password resets


def request_password_reset(email: str) -> None:
    """Email a reset link if ``email`` is an active, set-up account. Silent
    either way, so the response doesn't reveal which emails have accounts."""
    if not settings.EMAIL_ENABLED:
        return
    try:
        email = _clean_email(email)
    except Exception:
        return
    user = User.objects.filter(
        email__iexact=email, is_active=True, is_verified=True
    ).first()
    if user is None:
        return
    recent = AccountToken.objects.filter(
        user=user,
        purpose=Purpose.PASSWORD_RESET,
        created_at__gt=timezone.now() - RESET_REQUEST_COOLDOWN,
    ).exists()
    if recent:
        return
    with transaction.atomic():
        link = issue_link(user, Purpose.PASSWORD_RESET)
        queue_email(user, Purpose.PASSWORD_RESET, link)


@dataclass
class LinkResult:
    purpose: str
    link: str
    emailed: bool


@transaction.atomic
def send_password_reset(actor, user_id) -> LinkResult:
    """Admin-issued reset link. A user still pending gets a fresh invite."""
    user = get_managed_user(actor, user_id)
    if not user.is_active:
        _fail('auth.user_disabled')
    purpose = Purpose.INVITE if user.is_pending else Purpose.PASSWORD_RESET
    link = issue_link(user, purpose, created_by=actor)
    emailed = queue_email(user, purpose, link, inviter=_display_name(actor))
    return LinkResult(purpose=purpose, link=link, emailed=emailed)


@transaction.atomic
def reset_password(raw: str, new_password: str) -> User:
    token = find_token(raw, Purpose.PASSWORD_RESET)
    if token is None:
        _fail('auth.link_invalid')
    user = token.user
    _set_password(user, new_password)
    user.save(update_fields=['password', 'updated_at'])
    _retire_tokens(user)
    revoke_sessions(user)
    return user


# ---------------------------------------------------- platform user management

USER_STATUSES = ('ACTIVE', 'INVITED', 'DISABLED')


def list_users(actor, search: str = '', status: str | None = None) -> QuerySet:
    require_superuser(actor)
    users = User.objects.all().order_by('first_name', 'last_name', 'email')
    if search:
        term = search.strip()
        users = users.filter(
            Q(email__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(user_name__icontains=term)
        )
    if status == 'ACTIVE':
        users = users.filter(is_active=True, is_verified=True)
    elif status == 'INVITED':
        users = users.filter(is_active=True, is_verified=False)
    elif status == 'DISABLED':
        users = users.filter(is_active=False)
    return users


def get_managed_user(actor, user_id) -> User:
    require_superuser(actor)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        _fail('auth.user_not_found')
    return user


@transaction.atomic
def update_user(
    actor,
    user_id,
    *,
    first_name: str,
    last_name: str,
    user_name: str,
    email: str,
    phone: str | None = None,
) -> User:
    user = get_managed_user(actor, user_id)
    first_name, last_name = first_name.strip(), last_name.strip()
    user_name = user_name.strip()
    phone = (phone or '').strip() or None
    if not first_name or not last_name:
        _fail('auth.name_required')
    if not user_name:
        _fail('auth.username_required')
    email = _clean_email(email)

    others = User.objects.exclude(pk=user.pk)
    if others.filter(user_name__iexact=user_name).exists():
        _fail('auth.username_taken')
    if others.filter(email__iexact=email).exists():
        _fail('auth.email_taken')
    if phone and others.filter(phone=phone).exists():
        _fail('auth.phone_taken')

    user.first_name, user.last_name = first_name, last_name
    user.user_name, user.email, user.phone = user_name, email, phone
    user.save(
        update_fields=[
            'first_name',
            'last_name',
            'user_name',
            'email',
            'phone',
            'updated_at',
        ]
    )
    return user


@transaction.atomic
def set_user_active(actor, user_id, active: bool) -> User:
    user = get_managed_user(actor, user_id)
    if user.pk == actor.pk:
        _fail('auth.cannot_change_self')
    if user.is_active == active:
        return user
    user.is_active = active
    user.save(update_fields=['is_active', 'updated_at'])
    if not active:
        # Disabled users are rejected on every request already; this also
        # stops refreshes and kills any outstanding links.
        revoke_sessions(user)
        _retire_tokens(user)
    return user


def sign_out_user(actor, user_id) -> User:
    user = get_managed_user(actor, user_id)
    revoke_sessions(user)
    return user
