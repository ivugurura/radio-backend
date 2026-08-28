import graphene
from graphql_jwt.decorators import login_required

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
            raise Exception("Studio not found")
        if not can_manage_streaming_credential(info.context.user, studio):
            raise Exception("Not authorized to rotate streaming credentials")
        regenerate_streaming_credential(studio)
        return RegenerateStreamingCredential(
            streaming_config=_build_streaming_config(studio)
        )


class StreamingMutations(graphene.ObjectType):
    regenerate_streaming_credential = RegenerateStreamingCredential.Field()
