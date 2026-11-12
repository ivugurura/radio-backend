import graphene
from django.db.models import Q

from apps.medias.models import Track
from apps.medias.schema.types import TrackConnection
from apps.studio.services.permissions import Perm, require_perm


class MediasQuery(graphene.ObjectType):
    tracks = graphene.relay.ConnectionField(
        TrackConnection,
        studio_slug=graphene.String(required=True),
        state=graphene.String(),
        search=graphene.String(),
    )

    @require_perm(Perm.VIEW_MEDIA, studio_arg="studio_slug")
    def resolve_tracks(self, info, studio, state=None, search=None, **kwargs):
        qs = (
            Track.objects.filter(studio=studio)
            .select_related("is_duplicate_of")
            .order_by("-created_at")
        )
        if state:
            qs = qs.filter(state=state)
        if search:
            qs = qs.filter(title__icontains=search)
        return qs
