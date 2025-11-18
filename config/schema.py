import graphene
import graphql_jwt

from apps.medias.schema.mutations import MediasMutations
from apps.medias.schema.queries import MediasQuery
from apps.studio.schema.queries import ListenerQuery
from apps.users.schema.mutations import UserMutations
from apps.users.schema.queries import UserQuery


class Query(
    UserQuery,
    MediasQuery,
    ListenerQuery,
    graphene.ObjectType,
):
    # Root-level query composition
    health = graphene.String(description="Health check field")

    def resolve_health(root, info):
        return "OK"


class Mutation(
    UserMutations,
    MediasMutations,
    graphene.ObjectType,
):
    token_auth = graphql_jwt.ObtainJSONWebToken.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
