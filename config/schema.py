import graphene

from apps.users.schema.mutations import UserMutations
from apps.users.schema.queries import UserQuery


class Query(
    UserQuery,
    graphene.ObjectType,
):
    # Root-level query composition
    health = graphene.String(description="Health check field")

    def resolve_health(root, info):
        return "OK"


class Mutation(
    UserMutations,
    graphene.ObjectType,
):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)
