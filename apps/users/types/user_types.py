import graphene
from graphene_django import DjangoObjectType

from apps.studio.models.base import StudioMembership
from apps.studio.schema.types import StudioAccess, StudioRole
from apps.studio.services.permissions import (
    Perm,
    accessible_studios,
    can_assign_role,
    get_permissions,
)
from apps.users.models import User


class UserType(DjangoObjectType):
    is_superuser = graphene.Boolean(required=True)
    is_pending = graphene.Boolean(
        required=True, description="Invited but hasn't set a password yet"
    )
    studio_access = graphene.List(
        graphene.NonNull(StudioAccess),
        required=True,
        description="Studios this user can open in the dashboard (own user only)",
    )

    class Meta:
        model = User
        fields = ("id", "user_name", "email", "first_name", "last_name", "timezone")

    def resolve_is_superuser(user, info):
        return bool(user.is_superuser)

    def resolve_is_pending(user, info):
        return user.is_pending

    def resolve_studio_access(user, info):
        # Only for the signed-in user; other users' access is not exposed
        # (e.g. through studioMembers { user { studioAccess } }).
        viewer = info.context.user
        if not viewer.is_authenticated or viewer.pk != user.pk:
            return []
        # Use the request's user so its role cache is primed and reused.
        result = []
        for studio, role in accessible_studios(viewer):
            perms = get_permissions(viewer, studio)
            assignable = []
            if Perm.MANAGE_MEMBERS in perms:
                assignable = [
                    r
                    for r in StudioMembership.Role.values
                    if can_assign_role(viewer, studio, r)
                ]
            result.append(
                StudioAccess(
                    studio_id=studio.slug,
                    display_name=studio.display_name,
                    role=role,
                    permissions=sorted(p.value for p in perms),
                    assignable_roles=assignable,
                )
            )
        return result


UserStatus = graphene.Enum(
    "UserStatus",
    [("ACTIVE", "ACTIVE"), ("INVITED", "INVITED"), ("DISABLED", "DISABLED")],
    description="ACTIVE: can sign in. INVITED: hasn't accepted the invite yet. "
    "DISABLED: blocked from signing in.",
)


class UserStudioRole(graphene.ObjectType):
    studio_id = graphene.String(required=True, description="Studio slug")
    display_name = graphene.String(required=True)
    role = graphene.Field(StudioRole, required=True)


class ManagedUser(graphene.ObjectType):
    """A user account as platform admins see it. Resolves from a User."""

    id = graphene.UUID(required=True)
    email = graphene.String(required=True)
    first_name = graphene.String(required=True)
    last_name = graphene.String(required=True)
    user_name = graphene.String(required=True)
    phone = graphene.String()
    is_superuser = graphene.Boolean(required=True)
    status = graphene.Field(UserStatus, required=True)
    last_login = graphene.DateTime()
    created_at = graphene.DateTime()
    studios = graphene.List(graphene.NonNull(UserStudioRole), required=True)

    def resolve_status(user, info):
        if not user.is_active:
            return "DISABLED"
        if user.is_pending:
            return "INVITED"
        return "ACTIVE"

    def resolve_studios(user, info):
        # Prefetched by the users query; falls back to a query otherwise.
        memberships = [
            m
            for m in user.studio_memberships.all()
            if m.deleted_at is None and m.studio.deleted_at is None
        ]
        return [
            UserStudioRole(
                studio_id=m.studio.slug,
                display_name=m.studio.display_name,
                role=m.role,
            )
            for m in sorted(memberships, key=lambda m: m.studio.slug)
        ]
