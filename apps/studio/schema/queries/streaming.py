import graphene
from django.conf import settings

from apps.studio.schema.types import StreamingConfig
from apps.studio.services.helpers import get_or_create_streaming_credential
from apps.studio.services.permissions import Perm, require_perm


def _build_streaming_config(studio) -> StreamingConfig:
    credential = get_or_create_streaming_credential(studio)
    return StreamingConfig(
        studio_id=studio.slug,
        host=settings.STREAMING_INGEST_HOST,
        port=settings.STREAMING_INGEST_PORT,
        mount=f"/studios/{studio.slug}/live",
        protocol="Icecast 2 (SOURCE)",
        username=credential.username,
        password=credential.get_password(),
        format="MP3",
        bitrate_kbps=studio.default_br_kbps,
        sample_rate_hz=studio.default_sr_hz,
        channels=studio.default_ch,
        rotated_at=credential.rotated_at,
    )


class StreamingQuery(graphene.ObjectType):
    streaming_config = graphene.Field(
        StreamingConfig,
        studio_id=graphene.String(required=True),
    )

    @require_perm(Perm.VIEW_STREAM_CREDS)
    def resolve_streaming_config(self, info, studio):
        return _build_streaming_config(studio)
