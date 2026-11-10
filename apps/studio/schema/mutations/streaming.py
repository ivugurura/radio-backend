import graphene

from apps.studio.schema.queries.streaming import _build_streaming_config
from apps.studio.schema.types import StreamingConfig
from apps.studio.services.helpers import regenerate_streaming_credential
from apps.studio.services.permissions import Perm, require_perm


class RegenerateStreamingCredential(graphene.Mutation):
    class Arguments:
        studio_id = graphene.String(required=True)

    streaming_config = graphene.Field(StreamingConfig)

    @require_perm(Perm.ROTATE_STREAM_CREDS)
    def mutate(self, info, studio):
        regenerate_streaming_credential(studio)
        return RegenerateStreamingCredential(
            streaming_config=_build_streaming_config(studio)
        )


class StreamingMutations(graphene.ObjectType):
    regenerate_streaming_credential = RegenerateStreamingCredential.Field()
