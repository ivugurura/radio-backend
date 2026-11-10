from decimal import Decimal

import graphene
from graphql_jwt.decorators import login_required

from apps.common.translations import translate
from apps.studio.schema.queries.settings import build_studio_settings
from apps.studio.schema.types import StudioSettings
from apps.studio.services.helpers import get_studio
from apps.studio.services.permissions import Perm, has_perm

# Typical streaming targets sit between -16 and -14 LUFS; outside this range
# the output is either too quiet to hear or squashed and distorted.
LOUDNESS_RANGE = (-24.0, -9.0)
DISPLAY_NAME_MAX = 120


class UpdateStudioSettings(graphene.Mutation):
    """Edit a studio's name, description and loudness processing (OWNER/ADMIN)."""

    class Arguments:
        studio_id = graphene.String(required=True)
        display_name = graphene.String(required=True)
        description = graphene.String(required=True)
        auto_normalize = graphene.Boolean(required=True)
        loudness_target_lufs = graphene.Float(required=True)

    studio_settings = graphene.Field(StudioSettings)

    @login_required
    def mutate(
        self,
        info,
        studio_id: str,
        display_name: str,
        description: str,
        auto_normalize: bool,
        loudness_target_lufs: float,
    ):
        user = info.context.user
        studio = get_studio(studio_id)
        if not studio:
            raise Exception(translate("studio.studio_not_found"))
        if not has_perm(user, studio, Perm.EDIT_SETTINGS):
            raise Exception(translate("studio.not_authorized_settings"))

        display_name = display_name.strip()
        if not display_name or len(display_name) > DISPLAY_NAME_MAX:
            raise Exception(
                translate("studio.invalid_display_name", max=DISPLAY_NAME_MAX)
            )
        low, high = LOUDNESS_RANGE
        if not low <= loudness_target_lufs <= high:
            raise Exception(translate("studio.invalid_loudness", low=low, high=high))

        studio.display_name = display_name
        studio.description = description.strip()
        studio.auto_normalize = auto_normalize
        studio.loudness_target_lufs = Decimal(str(round(loudness_target_lufs, 1)))
        studio.save(
            update_fields=[
                "display_name",
                "description",
                "auto_normalize",
                "loudness_target_lufs",
            ]
        )
        return UpdateStudioSettings(studio_settings=build_studio_settings(studio, user))


class StudioSettingsMutations(graphene.ObjectType):
    update_studio_settings = UpdateStudioSettings.Field()
