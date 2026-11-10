import graphene

from apps.studio.models.base import Studio
from apps.studio.schema.member_types import StudioMember
from apps.studio.services.members import list_members
from apps.studio.services.permissions import Perm, require_perm


class StudioMembersQuery(graphene.ObjectType):
    studio_members = graphene.List(
        graphene.NonNull(StudioMember),
        required=True,
        studio_id=graphene.String(required=True),
    )

    @require_perm(Perm.MANAGE_MEMBERS)
    def resolve_studio_members(self, info, studio: Studio):
        return list_members(info.context.user, studio)
