import graphene
import graphql_jwt

from apps.chat.schema.queries import ChatQuery
from apps.medias.schema.mutations import MediasMutations
from apps.medias.schema.queries import MediasQuery
from apps.studio.schema.mutations.streaming import StreamingMutations
from apps.studio.schema.queries.dashboard import DashboardQuery
from apps.studio.schema.queries.listeners import ListenerQuery
from apps.studio.schema.queries.streaming import StreamingQuery
from apps.users.schema.mutations import UserMutations
from apps.users.schema.queries import UserQuery


class Query(
    UserQuery,
    MediasQuery,
    ListenerQuery,
    DashboardQuery,
    StreamingQuery,
    ChatQuery,
    graphene.ObjectType,
):
    health = graphene.String(description="Health check field")

    def resolve_health(root, info):
        return "OK"


class Mutation(
    UserMutations,
    MediasMutations,
    StreamingMutations,
    graphene.ObjectType,
):
    token_auth = graphql_jwt.ObtainJSONWebToken.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
