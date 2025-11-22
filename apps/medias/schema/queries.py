import graphene

from apps.medias.models import Track
from apps.medias.schema.types import TrackConnection
from apps.studio.services.helpers import get_studio


class MediasQuery(graphene.ObjectType):
    tracks = graphene.relay.ConnectionField(
        TrackConnection,
        studio_slug=graphene.String(required=True),
        state=graphene.String(),
        search=graphene.String(),
    )

    def resolve_tracks(self, info, studio_slug, state=None, search=None, **kwargs):
        studio = get_studio(studio_slug)
        qs = Track.objects.filter(studio=studio).order_by("-created_at")
        if state:
            qs = qs.filter(state=state)
        if search:
            qs = qs.filter(title__icontains=search)
        return qs
