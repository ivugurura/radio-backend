import logging

import graphene
from graphql_jwt.decorators import login_required

from apps.common.translations import translate
from apps.studio.services.helpers import can_control_playback, get_studio
from apps.studio.services.studio_control import StudioControlError, skip_track

logger = logging.getLogger(__name__)


class SkipTrack(graphene.Mutation):
    """Skip the AutoDJ track on air. radio-studio is only reachable from the
    backend for this, so the admin UI never holds the studio token."""

    class Arguments:
        studio_id = graphene.String(required=True)

    ok = graphene.Boolean(required=True)

    @login_required
    def mutate(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            raise Exception(translate("studio.studio_not_found"))
        if not can_control_playback(info.context.user, studio):
            raise Exception(translate("studio.not_authorized_skip"))
        try:
            skip_track(studio.slug)
        except StudioControlError as exc:
            logger.warning("skip_track failed for studio=%s: %s", studio.slug, exc)
            if exc.unreachable:
                raise Exception(translate("studio.studio_unreachable")) from exc
            raise Exception(translate("studio.skip_failed", reason=str(exc))) from exc
        logger.info(
            "user=%s skipped the current track on studio=%s",
            info.context.user.pk,
            studio.slug,
        )
        return SkipTrack(ok=True)


class PlaybackMutations(graphene.ObjectType):
    skip_track = SkipTrack.Field()
