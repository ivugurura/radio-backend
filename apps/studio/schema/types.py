import graphene


class CountryCount(graphene.ObjectType):
    code = graphene.String(required=True)   # ISO-3166 alpha-2 (e.g., "RW")
    count = graphene.Int(required=True)


class ListenerOverview(graphene.ObjectType):
    studio_id = graphene.String(required=True)
    active_now = graphene.Int(required=True)
    peak_last_hour = graphene.Int(required=True)
    peak_last_24h = graphene.Int(required=True)
    listener_minutes_last_24h = graphene.Int(required=True)
    countries = graphene.List(graphene.NonNull(CountryCount), required=True)
