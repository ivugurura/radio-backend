import datetime
import math
import os

import graphene
from django.db.models import (
    CharField,
    Count,
    DurationField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Cast, Coalesce, NullIf
from django.utils import timezone

from apps.medias.models import Track, TrackAsset
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

# Rough capacity budget for the VPS (2 vCPU, 8 GB RAM, 100 GB disk, 8 TB/month).
# Disk is in GiB: a "100 GB" disk formats to ~93 GiB usable.
VPS_DISK_GB = 93
DISK_RESERVED_GB = {
    "system": 15,  # OS, packages, 4 GB swap, logs/journal
    "databases": 8,  # Postgres, Redis, local backups
    "web_apps": 10,  # prod + staging web app, FastAPI service
    "headroom": 10,  # ext4 reserved blocks, ffmpeg scratch, safety margin
}
STUDIOS_DISK_GB = VPS_DISK_GB - sum(DISK_RESERVED_GB.values())  # ~50 GiB

VPS_BANDWIDTH_BYTES = 8 * 10**12  # 8 TB per month
BANDWIDTH_RESERVED_BYTES = 1 * 10**12  # web apps, uploads, backups
STREAMING_BANDWIDTH_BYTES = VPS_BANDWIDTH_BYTES - BANDWIDTH_RESERVED_BYTES


# A session counts as a "listen" once it has lasted this long, the usual
# radio-measurement threshold. It filters out tune-ins that leave right away
# and connections that drop immediately.
MIN_LISTEN_DURATION = datetime.timedelta(seconds=30)

# Identifies the listener behind a session for unique-listener counts. Rows
# from before listener_key existed (or from older studio builds) fall back to
# their own id, i.e. each counts as a separate listener.
_LISTENER_IDENTITY = Coalesce(
    NullIf("listener_key", Value("")), Cast("id", output_field=CharField())
)


def _qualifying_listens(studio: Studio):
    """Sessions of ``studio`` that lasted at least MIN_LISTEN_DURATION.

    A session still open has no ended_at; its last_seen (refreshed by every
    studio flush) stands in for the end so far.
    """
    duration = ExpressionWrapper(
        Coalesce("ended_at", "last_seen") - F("started_at"),
        output_field=DurationField(),
    )
    return (
        ListenerSession.objects.filter(studio=studio)
        .annotate(duration=duration)
        .filter(duration__gte=MIN_LISTEN_DURATION)
    )


def _studio_quotas(studio: Studio) -> tuple[int, float]:
    """Split the studio budget evenly across active studios.

    Returns (listening_seconds_quota, disk_quota_gb) for the 30-day window.
    """
    studio_count = max(1, Studio.objects.filter(is_active=True).count())
    bytes_per_second = (studio.default_br_kbps or 128) * 1000 / 8
    listening_quota = int(
        STREAMING_BANDWIDTH_BYTES / bytes_per_second / studio_count)
    disk_quota_gb = round(STUDIOS_DISK_GB / studio_count, 1)
    return listening_quota, disk_quota_gb


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

        if target_span <= datetime.timedelta(hours=2):
            interval = "MINUTE"
        elif target_span <= datetime.timedelta(hours=30):
            interval = "MINUTE"
        else:
            has_five = ListenerStatBucket.objects.filter(
                studio=studio, interval="FIVE_MIN", bucket_start__gte=since
            ).exists()
            interval = "FIVE_MIN" if has_five else "HOUR"

        buckets = ListenerStatBucket.objects.filter(
            studio=studio, interval=interval, bucket_start__gte=since
        ).order_by("bucket_start")

        points = []

        # Downsample 24h range to every 3rd MINUTE bucket to keep point density reasonable
        for idx, b in enumerate(buckets):
            if interval == "MINUTE" and range == TimeRange.LAST_24_HOURS.value:
                if idx % 3 != 0:
                    continue
            active = b.active_peak or 0
            points.append(ListeningTrendPoint(ts=b.bucket_start, active=active))

        # The peak is always today's (UTC day, as in the summary), whatever the
        # charted range. Ties keep the earliest minute to reach that peak.
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        peak_bucket = (
            ListenerStatBucket.objects.filter(
                studio=studio,
                interval="MINUTE",
                bucket_start__gte=today_start,
                active_peak__gt=0,
            )
            .order_by("-active_peak", "bucket_start")
            .first()
        )
        peak_point = None
        if peak_bucket:
            peak_point = ListeningTrendPoint(
                ts=peak_bucket.bucket_start, active=peak_bucket.active_peak
            )

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
                uniqueToday=0,
                uniqueYesterday=0,
                uniqueLast7Days=0,
                uniqueLast30Days=0,
                uniqueLastMonth=0,
            )

        now = timezone.now()
        # Day boundaries in UTC
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - datetime.timedelta(days=1)
        seven_days_start = today_start - datetime.timedelta(days=7)
        thirty_days_start = today_start - datetime.timedelta(days=30)
        prev_thirty_days_start = today_start - datetime.timedelta(days=60)
        month_start = today_start.replace(day=1)
        last_month_start = (month_start - datetime.timedelta(days=1)).replace(day=1)

        windows = {
            "today": Q(started_at__gte=today_start),
            "yesterday": Q(started_at__gte=yesterday_start, started_at__lt=today_start),
            "last7": Q(started_at__gte=seven_days_start),
            "last30": Q(started_at__gte=thirty_days_start),
            "prev30": Q(
                started_at__gte=prev_thirty_days_start,
                started_at__lt=thirty_days_start,
            ),
            "last_month": Q(
                started_at__gte=last_month_start, started_at__lt=month_start
            ),
        }
        counts = (
            _qualifying_listens(studio)
            .filter(started_at__gte=min(prev_thirty_days_start, last_month_start))
            .aggregate(
                **{
                    f"{name}_listens": Count("id", filter=q)
                    for name, q in windows.items()
                },
                **{
                    f"{name}_unique": Count(_LISTENER_IDENTITY, distinct=True, filter=q)
                    for name, q in windows.items()
                },
            )
        )

        last30_cnt = counts["last30_listens"]
        prev30_cnt = counts["prev30_listens"]
        if prev30_cnt > 0:
            change_pct = ((last30_cnt - prev30_cnt) / prev30_cnt) * 100.0
        else:
            change_pct = 0.0

        return ListeningSummary(
            today=counts["today_listens"],
            yesterday=counts["yesterday_listens"],
            last7Days=counts["last7_listens"],
            last30Days=last30_cnt,
            last30DaysChangePct=change_pct,
            prev30Days=prev30_cnt,
            lastMonth=counts["last_month_listens"],
            uniqueToday=counts["today_unique"],
            uniqueYesterday=counts["yesterday_unique"],
            uniqueLast7Days=counts["last7_unique"],
            uniqueLast30Days=counts["last30_unique"],
            uniqueLastMonth=counts["last_month_unique"],
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
        thirty_days_ago = now - datetime.timedelta(days=30)
        minutes_sum = (
            ListenerStatBucket.objects.filter(
                studio=studio, interval="MINUTE", bucket_start__gte=thirty_days_ago
            ).aggregate(total=Sum("listener_minutes"))["total"]
            or 0
        )
        listening_seconds = int(minutes_sum * 60)

        # Disk usage: the recorded on-disk size of each live track's assets.
        upload_bytes = (
            TrackAsset.objects.filter(
                track__studio=studio, track__deleted_at__isnull=True
            ).aggregate(total=Sum("size_bytes"))["total"]
            or 0
        )
        disk_used_gb = float(upload_bytes) / (1024**3)

        # Env vars override the VPS-based estimate.
        default_listening_quota, default_disk_quota_gb = _studio_quotas(studio)
        listening_quota = int(
            os.getenv("LISTENING_SECONDS_QUOTA") or default_listening_quota
        )
        disk_quota_gb = float(os.getenv("DISK_QUOTA_GB") or default_disk_quota_gb)

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

        all_events = PlayEvent.objects.filter(
            studio=studio, track__isnull=False)

        # Current playing = ended_at is null (if multiple, take latest started/sequence)
        current_event = (
            all_events.filter(ended_at__isnull=True)
            .order_by("-started_at", "-sequence")
            .first()
        )
        if not current_event:
            current_event = all_events.order_by(
                "-started_at", "-sequence").first()
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
            ).order_by("-started_at", "-sequence")[:candidate_count]
        )
        after_candidates = list(
            all_events.filter(
                Q(started_at__gt=current_event.started_at)
                | Q(
                    started_at=current_event.started_at,
                    sequence__gt=current_event.sequence,
                )
            ).order_by("started_at", "sequence")[:candidate_count]
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

        timeline_events = list(reversed(before_events)) + \
            [current_event] + after_events
        items = []
        for ev in timeline_events:
            queue_item = to_queue_item(
                ev, is_current=ev.id == current_event.id)
            if queue_item:
                items.append(queue_item)

        return CurrentQueue(items=items[:limit])
