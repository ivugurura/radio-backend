import graphene
from graphql_jwt.decorators import login_required

from apps.common.translations import translate
from apps.studio.schema.queries.streaming import _build_streaming_config
from apps.studio.schema.types import StreamingConfig
from apps.studio.services.helpers import get_studio, regenerate_streaming_credential
from apps.studio.services.permissions import Perm, has_perm


class RegenerateStreamingCredential(graphene.Mutation):
    class Arguments:
        studio_id = graphene.String(required=True)

    streaming_config = graphene.Field(StreamingConfig)

    @login_required
    def mutate(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            raise Exception(translate("studio.studio_not_found"))
        if not has_perm(info.context.user, studio, Perm.ROTATE_STREAM_CREDS):
            raise Exception(translate("studio.not_authorized_rotate"))
        regenerate_streaming_credential(studio)
        return RegenerateStreamingCredential(
            streaming_config=_build_streaming_config(studio)
        )


class StreamingMutations(graphene.ObjectType):
    regenerate_streaming_credential = RegenerateStreamingCredential.Field()
