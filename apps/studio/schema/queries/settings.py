import graphene
from graphql_jwt.decorators import login_required

from apps.studio.models.base import Studio
from apps.studio.schema.types import StudioSettings
from apps.studio.services.helpers import can_manage_studio_settings, get_studio


def build_studio_settings(studio: Studio, user) -> StudioSettings:
    return StudioSettings(
        studio_id=studio.slug,
        display_name=studio.display_name,
        description=studio.description,
        auto_normalize=studio.auto_normalize,
        loudness_target_lufs=float(studio.loudness_target_lufs),
        bitrate_kbps=studio.default_br_kbps,
        sample_rate_hz=studio.default_sr_hz,
        channels=studio.default_ch,
        can_edit=can_manage_studio_settings(user, studio),
    )


class StudioSettingsQuery(graphene.ObjectType):
    studio_settings = graphene.Field(
        StudioSettings, studio_id=graphene.String(required=True)
    )

    @login_required
    def resolve_studio_settings(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            return None
        return build_studio_settings(studio, info.context.user)
