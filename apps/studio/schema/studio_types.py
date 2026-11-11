import graphene

from apps.studio.models.base import Studio


class ManagedStudio(graphene.ObjectType):
    """A studio as platform admins see it on the studio management page."""

    studio_id = graphene.String(required=True, description="Studio slug")
    display_name = graphene.String(required=True)
    description = graphene.String(required=True)
    is_active = graphene.Boolean(required=True)
    bitrate_kbps = graphene.Int(required=True)
    sample_rate_hz = graphene.Int(required=True)
    channels = graphene.Int(required=True)
    member_count = graphene.Int(required=True)
    track_count = graphene.Int(required=True)
    has_streaming_credential = graphene.Boolean(required=True)
    created_at = graphene.DateTime()

    @staticmethod
    def from_studio(studio: Studio) -> 'ManagedStudio':
        # Counts come annotated from list_studios(); a studio fetched on its
        # own (after a mutation) is counted here.
        member_count = getattr(studio, 'member_count', None)
        if member_count is None:
            member_count = studio.memberships.count()
        track_count = getattr(studio, 'track_count', None)
        if track_count is None:
            track_count = studio.tracks.count()
        credential = getattr(studio, 'streaming_credential', None)
        return ManagedStudio(
            studio_id=studio.slug,
            display_name=studio.display_name,
            description=studio.description,
            is_active=studio.is_active,
            bitrate_kbps=studio.default_br_kbps,
            sample_rate_hz=studio.default_sr_hz,
            channels=studio.default_ch,
            member_count=member_count,
            track_count=track_count,
            has_streaming_credential=bool(credential) and credential.deleted_at is None,
            created_at=studio.created_at,
        )


class PublicStudio(graphene.ObjectType):
    """An active studio, as the public listener page needs it."""

    studio_id = graphene.String(required=True, description="Studio slug")
    display_name = graphene.String(required=True)
