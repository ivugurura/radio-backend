import graphene
from django.conf import settings

from apps.common.translations import translate
from apps.studio.schema.types import StreamingConfig
from apps.studio.services.helpers import (
    can_manage_streaming_credential,
    get_or_create_streaming_credential,
    get_studio,
)


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

    def resolve_streaming_config(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            return None
        if not can_manage_streaming_credential(info.context.user, studio):
            raise Exception(translate("studio.not_authorized_view"))
        return _build_streaming_config(studio)
