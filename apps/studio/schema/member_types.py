import graphene

from apps.studio.schema.types import StudioRole
from apps.studio.services.members import can_manage_member
from apps.users.types.user_types import UserType


class StudioMember(graphene.ObjectType):
    """A user's membership in a studio. Resolves from a StudioMembership."""

    id = graphene.UUID(required=True)
    user = graphene.Field(UserType, required=True)
    role = graphene.Field(StudioRole, required=True)
    created_at = graphene.DateTime()
    can_manage = graphene.Boolean(
        required=True,
        description="Whether the viewer may change this member's role or remove them",
    )

    def resolve_can_manage(membership, info):
        return can_manage_member(info.context.user, membership)
