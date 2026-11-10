import graphene

from apps.studio.models.base import Studio
from apps.studio.schema.member_types import StudioMember
from apps.studio.schema.types import StudioRole
from apps.studio.services.members import remove_member, update_member_role
from apps.studio.services.permissions import Perm, require_perm


class UpdateStudioMemberRole(graphene.Mutation):
    class Arguments:
        studio_id = graphene.String(required=True)
        user_id = graphene.UUID(required=True)
        role = StudioRole(required=True)

    member = graphene.Field(StudioMember, required=True)

    @require_perm(Perm.MANAGE_MEMBERS)
    def mutate(self, info, studio: Studio, user_id, role):
        member = update_member_role(info.context.user, studio, user_id, role)
        return UpdateStudioMemberRole(member=member)


class RemoveStudioMember(graphene.Mutation):
    class Arguments:
        studio_id = graphene.String(required=True)
        user_id = graphene.UUID(required=True)

    ok = graphene.Boolean(required=True)

    @require_perm(Perm.MANAGE_MEMBERS)
    def mutate(self, info, studio: Studio, user_id):
        remove_member(info.context.user, studio, user_id)
        return RemoveStudioMember(ok=True)


class StudioMemberMutations(graphene.ObjectType):
    update_studio_member_role = UpdateStudioMemberRole.Field()
    remove_studio_member = RemoveStudioMember.Field()
