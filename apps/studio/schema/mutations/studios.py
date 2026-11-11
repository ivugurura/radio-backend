import graphene
from graphql_jwt.decorators import login_required

from apps.studio.schema.studio_types import ManagedStudio
from apps.studio.services import studios


class CreateStudio(graphene.Mutation):
    """Create a studio for a language that has none (superusers only). The
    audio format follows the platform defaults and can't be chosen."""

    class Arguments:
        studio_id = graphene.String(
            required=True, description="Slug: a supported language code"
        )
        display_name = graphene.String(required=True)
        description = graphene.String()
        owner_user_id = graphene.UUID(description="Existing user to make OWNER")

    studio = graphene.Field(ManagedStudio, required=True)

    @login_required
    def mutate(self, info, studio_id, display_name, description='', owner_user_id=None):
        studio = studios.create_studio(
            info.context.user,
            slug=studio_id,
            display_name=display_name,
            description=description or '',
            owner_user_id=owner_user_id,
        )
        return CreateStudio(studio=ManagedStudio.from_studio(studio))


class SetStudioActive(graphene.Mutation):
    """Deactivate (or reactivate) a studio (superusers only). radio-studio
    stops serving a deactivated studio on its next sync."""

    class Arguments:
        studio_id = graphene.String(required=True)
        active = graphene.Boolean(required=True)

    studio = graphene.Field(ManagedStudio, required=True)

    @login_required
    def mutate(self, info, studio_id, active):
        studio = studios.set_studio_active(info.context.user, studio_id, active)
        return SetStudioActive(studio=ManagedStudio.from_studio(studio))


class StudioAdminMutations(graphene.ObjectType):
    create_studio = CreateStudio.Field()
    set_studio_active = SetStudioActive.Field()
