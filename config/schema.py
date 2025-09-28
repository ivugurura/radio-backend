import accounts.schema as accounts_schema
import graphene


class Query(
    accounts_schema.Query,
    graphene.ObjectType,
):
    # Root-level query composition
    health = graphene.String(description="Health check field")

    def resolve_health(root, info):
        return "OK"


class Mutation(
    accounts_schema.Mutation,
    graphene.ObjectType,
):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)
