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
    points = graphene.List(graphene.NonNull(ListeningTrendPoint), required=True)
    peak = graphene.Field(ListeningTrendPoint)


class ListeningSummary(graphene.ObjectType):
    today = graphene.Int(required=True)
    yesterday = graphene.Int(required=True)
    last7Days = graphene.Int(required=True)
    last30Days = graphene.Int(required=True)
    last30DaysChangePct = graphene.Float(required=True)
    prev30Days = graphene.Int(required=True)
    lastMonth = graphene.Int(required=True)
    # Distinct listeners behind the listens above (a listener who tunes in
    # three times today is 3 listens, 1 unique listener).
    uniqueToday = graphene.Int(required=True)
    uniqueYesterday = graphene.Int(required=True)
    uniqueLast7Days = graphene.Int(required=True)
    uniqueLast30Days = graphene.Int(required=True)
    uniqueLastMonth = graphene.Int(required=True)


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


class StreamingConfig(graphene.ObjectType):
    studio_id = graphene.String(required=True)
    host = graphene.String(required=True)
    port = graphene.Int(required=True)
    mount = graphene.String(required=True)
    protocol = graphene.String(required=True)
    username = graphene.String(required=True)
    password = graphene.String(required=True)
    format = graphene.String(required=True)
    bitrate_kbps = graphene.Int(required=True)
    sample_rate_hz = graphene.Int(required=True)
    channels = graphene.Int(required=True)
    rotated_at = graphene.DateTime()


class StudioSettings(graphene.ObjectType):
    studio_id = graphene.String(required=True)
    display_name = graphene.String(required=True)
    description = graphene.String(required=True)
    auto_normalize = graphene.Boolean(required=True)
    loudness_target_lufs = graphene.Float(required=True)
    # Read-only: the audio format has to match radio-studio, the live encoder
    # and every transcoded library track, so it is not editable from the UI.
    bitrate_kbps = graphene.Int(required=True)
    sample_rate_hz = graphene.Int(required=True)
    channels = graphene.Int(required=True)
    can_edit = graphene.Boolean(required=True)
