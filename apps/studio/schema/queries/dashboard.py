import datetime
import math
import os

import graphene
from django.db.models import Q, Sum
from django.utils import timezone

from apps.medias.models import Track, UploadSession
from apps.studio.models.analytics import ListenerSession, ListenerStatBucket, PlayEvent
from apps.studio.models.base import Studio
from apps.studio.schema.types import (
    CurrentQueue,
    ListeningSummary,
    ListeningTrend,
    ListeningTrendPoint,
    QueueItem,
    StudioCapacity,
    TimeRange,
)
from apps.studio.services.helpers import get_studio


class DashboardQuery(graphene.ObjectType):
    listening_trend = graphene.Field(
        ListeningTrend,
        studio_id=graphene.String(required=True),
        range=graphene.Argument(TimeRange, default_value=TimeRange.LAST_90_MIN),
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

        buckets = ListenerStatBucket.objects.filter(
            studio=studio, interval=interval, bucket_start__gte=since
        ).order_by("bucket_start")

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
            started_at__gte=yesterday_start, started_at__lt=today_start
        ).count()
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
        disk_used_gb = float(upload_bytes) / (1024**3)

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
        limit = max(limit or 0, 5)
        studio = get_studio(studio_id)
        if not studio:
            return CurrentQueue(items=[])

        all_events = PlayEvent.objects.filter(studio=studio, track__isnull=False)

        # Current playing = ended_at is null (if multiple, take latest started/sequence)
        current_event = (
            all_events.filter(ended_at__isnull=True)
            .order_by("-started_at", "-sequence")
            .first()
        )
        if not current_event:
            current_event = all_events.order_by("-started_at", "-sequence").first()
        if not current_event:
            return CurrentQueue(items=[])

        before_target = (limit - 1) // 2
        after_target = limit - 1 - before_target
        # Pull a wider slice so we can deduplicate by track and still fill targets.
        candidate_count = max(limit * 4, 12)

        before_candidates = list(
            all_events.filter(
                Q(started_at__lt=current_event.started_at)
                | Q(
                    started_at=current_event.started_at,
                    sequence__lt=current_event.sequence,
                )
            )
            .order_by("-started_at", "-sequence")[:candidate_count]
        )
        after_candidates = list(
            all_events.filter(
                Q(started_at__gt=current_event.started_at)
                | Q(
                    started_at=current_event.started_at,
                    sequence__gt=current_event.sequence,
                )
            )
            .order_by("started_at", "sequence")[:candidate_count]
        )

        used_track_ids = set()

        def to_queue_item(ev: PlayEvent, is_current: bool = False):
            track = ev.track
            if not track:
                return None
            return QueueItem(
                id=track.id,
                title=track.title or "Untitled",
                artist=track.artist or "",
                startedAt=ev.started_at,
                durationSec=track.duration_seconds,
                coverUrl=None,
                isCurrent=is_current,
            )

        current_track_id = current_event.track_id
        if current_track_id:
            used_track_ids.add(current_track_id)

        before_events = []
        for ev in before_candidates:
            if len(before_events) >= before_target:
                break
            if not ev.track_id or ev.track_id in used_track_ids:
                continue
            used_track_ids.add(ev.track_id)
            before_events.append(ev)

        after_events = []
        for ev in after_candidates:
            if len(after_events) >= after_target:
                break
            if not ev.track_id or ev.track_id in used_track_ids:
                continue
            used_track_ids.add(ev.track_id)
            after_events.append(ev)

        current_event_ids = {ev.id for ev in before_events}
        current_event_ids.update(ev.id for ev in after_events)
        current_event_ids.add(current_event.id)

        # Fill any missing slots, prioritizing older history first, then newer.
        if len(before_events) + len(after_events) + 1 < limit:
            missing = limit - (len(before_events) + len(after_events) + 1)
            for ev in before_candidates:
                if missing <= 0:
                    break
                if ev.id in current_event_ids:
                    continue
                if not ev.track_id or ev.track_id in used_track_ids:
                    continue
                used_track_ids.add(ev.track_id)
                current_event_ids.add(ev.id)
                before_events.append(ev)
                missing -= 1

            if missing > 0:
                for ev in after_candidates:
                    if missing <= 0:
                        break
                    if ev.id in current_event_ids:
                        continue
                    if not ev.track_id or ev.track_id in used_track_ids:
                        continue
                    used_track_ids.add(ev.track_id)
                    current_event_ids.add(ev.id)
                    after_events.append(ev)
                    missing -= 1

        timeline_events = list(reversed(before_events)) + [current_event] + after_events
        items = []
        for ev in timeline_events:
            queue_item = to_queue_item(ev, is_current=ev.id == current_event.id)
            if queue_item:
                items.append(queue_item)

        return CurrentQueue(items=items[:limit])
