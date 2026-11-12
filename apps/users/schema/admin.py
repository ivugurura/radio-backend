"""User management: platform-wide for superusers, invites for studio admins."""

import graphene
from django.db.models import Prefetch
from graphql_jwt.decorators import login_required

from apps.studio.models.base import StudioMembership
from apps.studio.schema.types import StudioRole
from apps.studio.services.helpers import get_studio
from apps.studio.services.permissions import check_perm
from apps.users.services import accounts
from apps.users.types.user_types import ManagedUser, UserStatus, UserType

MAX_PAGE_SIZE = 100


class UserPage(graphene.ObjectType):
    total_count = graphene.Int(required=True)
    items = graphene.List(graphene.NonNull(ManagedUser), required=True)


class AccountLinkPurpose(graphene.Enum):
    INVITE = "INVITE"
    PASSWORD_RESET = "PASSWORD_RESET"


def _value(enum_or_value):
    """Graphene enum args may arrive as the member or its value."""
    return getattr(enum_or_value, "value", enum_or_value)


class UserAdminQuery(graphene.ObjectType):
    users = graphene.Field(
        UserPage,
        required=True,
        search=graphene.String(),
        status=UserStatus(),
        limit=graphene.Int(default_value=25),
        offset=graphene.Int(default_value=0),
        description="Every account (superusers only)",
    )

    @login_required
    def resolve_users(self, info, search="", status=None, limit=25, offset=0):
        users = accounts.list_users(info.context.user, search or "", _value(status))
        limit = max(1, min(limit or 25, MAX_PAGE_SIZE))
        offset = max(0, offset or 0)
        page = users.prefetch_related(
            Prefetch(
                "studio_memberships",
                queryset=StudioMembership.objects.select_related("studio"),
            )
        )[offset : offset + limit]
        return UserPage(total_count=users.count(), items=list(page))


class InviteUser(graphene.Mutation):
    """Invite someone by email. Superusers may omit the studio; studio admins
    invite into their studio with a role they're allowed to grant. An existing
    account is added to the studio without a link."""

    class Arguments:
        email = graphene.String(required=True)
        first_name = graphene.String()
        last_name = graphene.String()
        studio_id = graphene.String()
        role = StudioRole()

    user = graphene.Field(UserType, required=True)
    created = graphene.Boolean(required=True, description="A new account was created")
    invite_link = graphene.String(
        description="One-time link to share; null for accounts that already have a password"
    )
    emailed = graphene.Boolean(required=True)

    @login_required
    def mutate(
        self, info, email, first_name="", last_name="", studio_id=None, role=None
    ):
        studio = None
        if studio_id:
            studio = get_studio(studio_id)
            check_perm(info.context.user, studio)
        result = accounts.invite_user(
            info.context.user,
            email,
            first_name or "",
            last_name or "",
            studio=studio,
            role=_value(role),
        )
        return InviteUser(
            user=result.user,
            created=result.created,
            invite_link=result.link,
            emailed=result.emailed,
        )


class UpdateUser(graphene.Mutation):
    class Arguments:
        user_id = graphene.UUID(required=True)
        first_name = graphene.String(required=True)
        last_name = graphene.String(required=True)
        user_name = graphene.String(required=True)
        email = graphene.String(required=True)
        phone = graphene.String()

    user = graphene.Field(ManagedUser, required=True)

    @login_required
    def mutate(
        self, info, user_id, first_name, last_name, user_name, email, phone=None
    ):
        user = accounts.update_user(
            info.context.user,
            user_id,
            first_name=first_name,
            last_name=last_name,
            user_name=user_name,
            email=email,
            phone=phone,
        )
        return UpdateUser(user=user)


class SetUserActive(graphene.Mutation):
    """Disable (or re-enable) an account. Disabling signs the user out
    everywhere and voids their pending links."""

    class Arguments:
        user_id = graphene.UUID(required=True)
        active = graphene.Boolean(required=True)

    user = graphene.Field(ManagedUser, required=True)

    @login_required
    def mutate(self, info, user_id, active):
        return SetUserActive(
            user=accounts.set_user_active(info.context.user, user_id, active)
        )


class SendPasswordReset(graphene.Mutation):
    """Issue a password-reset link (a fresh invite for users still pending)."""

    class Arguments:
        user_id = graphene.UUID(required=True)

    purpose = graphene.Field(AccountLinkPurpose, required=True)
    link = graphene.String(required=True)
    emailed = graphene.Boolean(required=True)

    @login_required
    def mutate(self, info, user_id):
        result = accounts.send_password_reset(info.context.user, user_id)
        return SendPasswordReset(
            purpose=str(result.purpose), link=result.link, emailed=result.emailed
        )


class SignOutUser(graphene.Mutation):
    """End every session of a user without disabling the account."""

    class Arguments:
        user_id = graphene.UUID(required=True)

    ok = graphene.Boolean(required=True)

    @login_required
    def mutate(self, info, user_id):
        accounts.sign_out_user(info.context.user, user_id)
        return SignOutUser(ok=True)


class UserAdminMutations(graphene.ObjectType):
    invite_user = InviteUser.Field()
    update_user = UpdateUser.Field()
    set_user_active = SetUserActive.Field()
    send_password_reset = SendPasswordReset.Field()
    sign_out_user = SignOutUser.Field()
