import os
import datetime
import math
import graphene
from django.utils import timezone
from django.db.models import Sum, Q

from apps.studio.models.analytics import (
    ListenerStatBucket,
    PlayEvent,
    ListenerSession
)
from apps.medias.models import Track, UploadSession
from apps.studio.models.base import Studio
from apps.studio.schema.types import (
    ListeningTrend,
    ListeningTrendPoint,
    ListeningSummary,
    StudioCapacity,
    CurrentQueue,
    QueueItem,
    TimeRange,
)
from apps.studio.services.helpers import get_studio


class DashboardQuery(graphene.ObjectType):
    listening_trend = graphene.Field(
        ListeningTrend,
        studio_id=graphene.String(required=True),
        range=graphene.Argument(
            TimeRange, default_value=TimeRange.LAST_90_MIN),
    )
    listening_summary_count = graphene.Field(
        ListeningSummary,
        studio_id=graphene.String(required=True),
    )
    studio_capacity = graphene.Field(
        StudioCapacity,
        studio_id=graphene.String(required=True),
    )
    current_queue = graphene.Field(
        CurrentQueue,
        studio_id=graphene.String(required=True),
        limit=graphene.Int(default_value=12),
    )

    # -------- Trend --------
    def resolve_listening_trend(self, info, studio_id: str, range: str):
        studio = get_studio(studio_id)
        if not studio:
            return ListeningTrend(points=[], peak=None)

        now = timezone.now()
        if range == TimeRange.LAST_7_DAYS.value:
            since = now - datetime.timedelta(days=7)
            target_span = datetime.timedelta(days=7)
        elif range == TimeRange.LAST_24_HOURS.value:
            since = now - datetime.timedelta(hours=24)
            target_span = datetime.timedelta(hours=24)
        else:  # LAST_90_MIN
            since = now - datetime.timedelta(minutes=90)
            target_span = datetime.timedelta(minutes=90)

        # Pick interval:
        # - If span <= 2h -> MINUTE
        # - If 2h < span <= 30h -> use MINUTE (optionally downsample)
        # - If 30h < span <= 7 days -> prefer FIVE_MIN; fallback to HOUR
        if target_span <= datetime.timedelta(hours=2):
            interval = "MINUTE"
        elif target_span <= datetime.timedelta(hours=30):
            interval = "MINUTE"
        else:
            # Attempt FIVE_MIN buckets; if none exist fall back to HOUR
            has_five = ListenerStatBucket.objects.filter(
                studio=studio, interval="FIVE_MIN", bucket_start__gte=since
            ).exists()
            interval = "FIVE_MIN" if has_five else "HOUR"

        buckets = (
            ListenerStatBucket.objects.filter(
                studio=studio, interval=interval, bucket_start__gte=since
            )
            .order_by("bucket_start")
        )

        points = []
        peak_point = None
        peak_val = -1

        # Optional downsampling for 24h range (keep every 3rd MINUTE bucket)
        for idx, b in enumerate(buckets):
            if interval == "MINUTE" and range == TimeRange.LAST_24_HOURS.value:
                if idx % 3 != 0:  # skip for density
                    continue
            active = b.active_peak or 0
            p = ListeningTrendPoint(ts=b.bucket_start, active=active)
            points.append(p)
            if active > peak_val:
                peak_val = active
                peak_point = p

        return ListeningTrend(points=points, peak=peak_point)

    # -------- Summary --------
    def resolve_listening_summary_count(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            return ListeningSummary(
                today=0,
                yesterday=0,
                last7Days=0,
                last30Days=0,
                last30DaysChangePct=0.0,
                prev30Days=0,
                lastMonth=0,
            )

        now = timezone.now()
        # Day boundaries in UTC
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - datetime.timedelta(days=1)
        seven_days_start = today_start - datetime.timedelta(days=7)
        thirty_days_start = today_start - datetime.timedelta(days=30)
        prev_thirty_days_start = today_start - datetime.timedelta(days=60)
        month_start = today_start.replace(day=1)
        last_month_end = month_start - datetime.timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        # Count "listens" as session starts (ListenerSession.started_at inside window)
        qs = ListenerSession.objects.filter(studio=studio)

        today_cnt = qs.filter(started_at__gte=today_start).count()
        yesterday_cnt = qs.filter(
            started_at__gte=yesterday_start, started_at__lt=today_start).count()
        last7_cnt = qs.filter(started_at__gte=seven_days_start).count()
        last30_cnt = qs.filter(started_at__gte=thirty_days_start).count()
        prev30_cnt = qs.filter(
            started_at__gte=prev_thirty_days_start, started_at__lt=thirty_days_start
        ).count()
        last_month_cnt = qs.filter(
            started_at__gte=last_month_start, started_at__lte=last_month_end
        ).count()

        if prev30_cnt > 0:
            change_pct = ((last30_cnt - prev30_cnt) / prev30_cnt) * 100.0
        else:
            change_pct = 0.0

        return ListeningSummary(
            today=today_cnt,
            yesterday=yesterday_cnt,
            last7Days=last7_cnt,
            last30Days=last30_cnt,
            last30DaysChangePct=change_pct,
            prev30Days=prev30_cnt,
            lastMonth=last_month_cnt,
        )

    # -------- Capacity --------
    def resolve_studio_capacity(self, info, studio_id: str):
        studio = get_studio(studio_id)
        if not studio:
            return StudioCapacity(
                listeningSeconds=0,
                listeningSecondsQuota=0,
                diskUsedGb=0.0,
                diskQuotaGb=0.0,
            )

        now = timezone.now()
        # Listening seconds: sum of listener_minutes in last 30 days * 60
        thirty_days_ago = now - datetime.timedelta(days=30)
        minutes_sum = (
            ListenerStatBucket.objects.filter(
                studio=studio, interval="MINUTE", bucket_start__gte=thirty_days_ago
            ).aggregate(total=Sum("listener_minutes"))["total"]
            or 0
        )
        listening_seconds = int(minutes_sum * 60)

        # Disk usage: approximate by summing size_bytes of finalized UploadSession
        upload_bytes = (
            UploadSession.objects.filter(studio=studio, finalized=True).aggregate(
                total=Sum("size_bytes")
            )["total"]
            or 0
        )
        disk_used_gb = float(upload_bytes) / (1024 ** 3)

        # Quotas via env or defaults
        listening_quota = int(
            os.getenv("LISTENING_SECONDS_QUOTA", "5400000")  # e.g., 1500 hours
        )
        disk_quota_gb = float(os.getenv("DISK_QUOTA_GB", "10"))

        return StudioCapacity(
            listeningSeconds=listening_seconds,
            listeningSecondsQuota=listening_quota,
            diskUsedGb=round(disk_used_gb, 4),
            diskQuotaGb=disk_quota_gb,
        )

    # -------- Current Queue --------
    def resolve_current_queue(self, info, studio_id: str, limit: int):
        studio = get_studio(studio_id)
        if not studio:
            return CurrentQueue(items=[])

        now = timezone.now()
        GRACE_PERIOD = datetime.timedelta(seconds=20)
        # Current playing = ended_at is null (if multiple, take latest started)
        current_event = (
            PlayEvent.objects.filter(studio=studio, ended_at__isnull=True)
            .order_by("-started_at")
            .first()
        )

        past_events = (
            PlayEvent.objects.filter(studio=studio, ended_at__isnull=False)
            .order_by("-started_at")[: limit]
        )
        # Reverse past events to show older first (like a timeline)
        past_events = list(reversed(list(past_events)))

        events = []
        if past_events:
            events.extend(past_events)
        if current_event:
            events.append(current_event)

        items = []
        for ev in events:
            track = ev.track
            if not track:
                continue
            items.append(
                QueueItem(
                    id=track.id,
                    title=track.title or "Untitled",
                    artist=track.artist or "",
                    startedAt=ev.started_at,
                    durationSec=track.duration_seconds,
                    coverUrl=None,  # TODO: add artwork field if available
                    isCurrent=current_event and ev.id == current_event.id,
                )
            )

        # If we have fewer than limit and can show more recent finished events:
        if len(items) < limit:
            extra = (
                PlayEvent.objects.filter(studio=studio)
                .exclude(id__in=[ev.id for ev in events])
                .order_by("-started_at")[: (limit - len(items))]
            )
            # Append (reverse for chronological)
            extra = list(reversed(list(extra)))
            for ev in extra:
                track = ev.track
                if not track:
                    continue
                items.append(
                    QueueItem(
                        id=track.id,
                        title=track.title or "Untitled",
                        artist=track.artist or "",
                        startedAt=ev.started_at,
                        durationSec=track.duration_seconds,
                        coverUrl=None,
                        isCurrent=False,
                    )
                )

        return CurrentQueue(items=items[:limit])
