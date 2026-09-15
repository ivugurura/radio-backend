import graphene
from graphql_jwt.decorators import login_required

from apps.common.translations import translate
from apps.studio.schema.queries.streaming import _build_streaming_config
from apps.studio.schema.types import StreamingConfig
from apps.studio.services.helpers import (
    can_manage_streaming_credential,
    get_studio,
    regenerate_streaming_credential,
)


class RegenerateStreamingCredential(graphene.Mutation):
    class Arguments:
        studio_id = graphene.String(required=True)

    streaming_config = graphene.Field(StreamingConfig)

    @login_required
    def mutate(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            raise Exception(translate("studio.studio_not_found"))
        if not can_manage_streaming_credential(info.context.user, studio):
            raise Exception(translate("studio.not_authorized_rotate"))
        regenerate_streaming_credential(studio)
        return RegenerateStreamingCredential(
            streaming_config=_build_streaming_config(studio)
        )


class StreamingMutations(graphene.ObjectType):
    regenerate_streaming_credential = RegenerateStreamingCredential.Field()
