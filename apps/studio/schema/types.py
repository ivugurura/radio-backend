import graphene


class TimeRange(graphene.Enum):
    LAST_90_MIN = "LAST_90_MIN"
    LAST_24_HOURS = "LAST_24_HOURS"
    LAST_7_DAYS = "LAST_7_DAYS"


class CountryCount(graphene.ObjectType):
    code = graphene.String(required=True)  # ISO-3166 alpha-2 (e.g., "RW")
    count = graphene.Int(required=True)


class ListenerOverview(graphene.ObjectType):
    studio_id = graphene.String(required=True)
    active_now = graphene.Int(required=True)
    peak_last_hour = graphene.Int(required=True)
    peak_last_24h = graphene.Int(required=True)
    listener_minutes_last_24h = graphene.Int(required=True)
    countries = graphene.List(graphene.NonNull(CountryCount), required=True)


class ListeningTrendPoint(graphene.ObjectType):
    ts = graphene.DateTime(required=True)
    active = graphene.Int(required=True)


class ListeningTrend(graphene.ObjectType):
    points = graphene.List(graphene.NonNull(
        ListeningTrendPoint), required=True)
    peak = graphene.Field(ListeningTrendPoint)


class ListeningSummary(graphene.ObjectType):
    today = graphene.Int(required=True)
    yesterday = graphene.Int(required=True)
    last7Days = graphene.Int(required=True)
    last30Days = graphene.Int(required=True)
    last30DaysChangePct = graphene.Float(required=True)
    prev30Days = graphene.Int(required=True)
    lastMonth = graphene.Int(required=True)


class StudioCapacity(graphene.ObjectType):
    listeningSeconds = graphene.Int(required=True)
    listeningSecondsQuota = graphene.Int(required=True)
    diskUsedGb = graphene.Float(required=True)
    diskQuotaGb = graphene.Float(required=True)


class QueueItem(graphene.ObjectType):
    id = graphene.UUID(required=True)
    title = graphene.String(required=True)
    artist = graphene.String()
    startedAt = graphene.DateTime()
    durationSec = graphene.Int()
    coverUrl = graphene.String()
    isCurrent = graphene.Boolean(required=True)


class CurrentQueue(graphene.ObjectType):
    items = graphene.List(graphene.NonNull(QueueItem), required=True)
