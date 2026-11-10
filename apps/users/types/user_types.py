import graphene
from graphene_django import DjangoObjectType

from apps.studio.models.base import StudioMembership
from apps.studio.schema.types import StudioAccess
from apps.studio.services.permissions import (
    Perm,
    accessible_studios,
    can_assign_role,
    get_permissions,
)
from apps.users.models import User


class UserType(DjangoObjectType):
    is_superuser = graphene.Boolean(required=True)
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
