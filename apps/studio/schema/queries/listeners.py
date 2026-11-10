import datetime

import graphene
from django.utils import timezone
from graphene import Argument

from apps.studio.models.analytics import ListenerSession, ListenerStatBucket
from apps.studio.models.base import Studio
from apps.studio.schema.types import CountryCount, ListenerOverview, TimeRange
from apps.studio.services.permissions import Perm, require_perm


class ListenerQuery(graphene.ObjectType):
    listener_overview = graphene.Field(
        ListenerOverview,
        studio_id=Argument(graphene.String, required=True),
        range=Argument(
            TimeRange, required=False, default_value=TimeRange.LAST_24_HOURS
        ),
    )

    @require_perm(Perm.VIEW_ANALYTICS)
    def resolve_listener_overview(
        self, info, studio: Studio, range: str = "LAST_24_HOURS"
    ):
        now = timezone.now()
        GRACE_PERIOD = datetime.timedelta(seconds=20)
        if range == TimeRange.LAST_7_DAYS.value:
            since = now - datetime.timedelta(days=7)
        else:
            since = now - datetime.timedelta(days=1)

        # Open sessions the studio reported recently. radio-studio already merges
        # a listener's reconnects and parallel tabs into one session, so this
        # counts listeners. ended_at drops a closed session at once; last_seen
        # covers the studio going away without reporting ends.
        open_sessions = ListenerSession.objects.filter(
            studio=studio,
            ended_at__isnull=True,
            last_seen__gte=now - GRACE_PERIOD,
        )
        active_now = open_sessions.count()

        minute_buckets = ListenerStatBucket.objects.filter(
            studio=studio, interval="MINUTE", bucket_start__gte=since
        )
        peak_last_24h = 0
        peak_last_hour = 0
        listener_minutes_last_24h = 0

        one_hour_ago = now - datetime.timedelta(hours=1)
        for b in minute_buckets:
            listener_minutes_last_24h += b.listener_minutes or 0
            if b.active_peak and b.active_peak > peak_last_24h:
                peak_last_24h = b.active_peak
            if (
                b.bucket_start >= one_hour_ago
                and b.active_peak
                and b.active_peak > peak_last_hour
            ):
                peak_last_hour = b.active_peak

        # Countries: use the most recent MINUTE bucket if available; otherwise derive from active sessions
        latest_bucket = (
            ListenerStatBucket.objects.filter(studio=studio, interval="MINUTE")
            .order_by("-bucket_start")
            .first()
        )
        countries_map = {}
        if latest_bucket and latest_bucket.countries_json:
            for code, cnt in latest_bucket.countries_json.items():
                try:
                    countries_map[code] = int(cnt or 0)
                except Exception:
                    continue
        else:
            for c in open_sessions.values_list("country", flat=True):
                if not c:
                    continue
                countries_map[c] = countries_map.get(c, 0) + 1

        countries = [
            CountryCount(code=k, count=v) for k, v in sorted(countries_map.items())
        ]

        return ListenerOverview(
            studio_id=str(studio.slug),
            active_now=active_now,
            peak_last_hour=peak_last_hour,
            peak_last_24h=peak_last_24h,
            listener_minutes_last_24h=listener_minutes_last_24h,
            countries=countries,
        )
