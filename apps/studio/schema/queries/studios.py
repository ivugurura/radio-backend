import graphene
from graphql_jwt.decorators import login_required

from apps.studio.models.base import Studio
from apps.studio.schema.studio_types import ManagedStudio, PublicStudio
from apps.studio.services import studios


class StudiosQuery(graphene.ObjectType):
    studios = graphene.List(
        graphene.NonNull(ManagedStudio),
        required=True,
        include_inactive=graphene.Boolean(default_value=True),
        description="Every studio (superusers only)",
    )
    available_studio_slugs = graphene.List(
        graphene.NonNull(graphene.String),
        required=True,
        description="Language codes a new studio may use (superusers only)",
    )
    public_studios = graphene.List(
        graphene.NonNull(PublicStudio),
        required=True,
        description="Active studios; open to anonymous listeners",
    )

    @login_required
    def resolve_studios(self, info, include_inactive=True):
        found = studios.list_studios(info.context.user, include_inactive)
        return [ManagedStudio.from_studio(s) for s in found]

    @login_required
    def resolve_available_studio_slugs(self, info):
        return studios.available_slugs(info.context.user)

    def resolve_public_studios(self, info):
        return [
            PublicStudio(studio_id=s.slug, display_name=s.display_name)
            for s in Studio.objects.filter(is_active=True).order_by('slug')
        ]
