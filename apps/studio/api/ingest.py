import json
import random
import time
import uuid

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.http import HttpRequest, JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.studio.models import ListenerSession, ListenerStatBucket, Studio
from apps.studio.services.helpers import get_studio


def server_response(message: str, status_code: int = 200) -> JsonResponse:
    """
    Helper function to create a standardized JSON response.

    Args:
        message (str): The message to include in the response.
        status_code (int, optional): The HTTP status code for the response. Defaults to 200.

    Returns:
        JsonResponse: A Django JsonResponse object with the specified message and status code.
    """
    return JsonResponse({"message": message}, status=status_code)


def _parse_iso(dt_str: str):
    if dt_str is None:
        return None
    return parse_datetime(dt_str)


def _bearer_token(req: HttpRequest) -> str:
    auth_header = req.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""


def _run_with_deadlock_retry(fn, attempts: int = 3, base_delay: float = 0.1):
    """
    Run ``fn`` (a callable that opens its own transaction) and retry it if
    PostgreSQL aborts it with "deadlock detected". Concurrent ingests for the
    same studio touch the same listener_sessions rows; the advisory lock in
    ``ingest_listener_events`` prevents most collisions, this is the safety net.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if "deadlock detected" not in str(exc) or attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2**attempt) + random.uniform(0, base_delay))


@csrf_exempt
@require_POST
def ingest_listener_events(request: HttpRequest, studio_slug: str) -> JsonResponse:
    """
    Endpoint to ingest listener events for a specific studio.

    Args:
        request (HttpRequest): The incoming HTTP request.
        studio_slug (str): The slug or ID of the studio.

    Returns:
        JsonResponse: A JSON response indicating success or failure.
    """
    token = _bearer_token(request)
    if not token:
        return server_response("Invalid token", status_code=401)
    expected = getattr(settings, "STUDIO_TOKEN", "")
    # print(expected)
    # if not token or token != expected:
    #     return server_response("Not authorized", status_code=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return server_response("Invalid JSON payload", status_code=400)
    studio = get_studio(studio_slug)
    if not studio:
        return server_response("Studio not found", status_code=404)

    sessions = payload.get("sessions") or []
    buckets = payload.get("buckets") or []

    # Deterministic ordering so that two ingest requests that overlap in time
    # always take row locks in the same order (otherwise concurrent flushes
    # deadlock on listener_sessions / listener_stat_buckets).
    sessions = sorted(sessions, key=lambda s: str(s.get("id") or ""))
    buckets = sorted(
        buckets,
        key=lambda b: (
            (b.get("interval") or "").upper(),
            str(b.get("bucket_start") or ""),
        ),
    )

    def _apply():
        inserted = 0
        updated = 0
        upserted = 0

        with transaction.atomic():
            # Serialize concurrent ingests for this studio.
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    [f"listener_ingest:{studio.pk}"],
                )

            # Upsert every ListenerSession in one statement.
            objs = []
            for s in sessions:
                s_id = s.get("id")
                if not s_id:
                    continue
                try:
                    s_id_uuid = uuid.UUID(s_id)
                except Exception:
                    s_id_uuid = uuid.uuid4()

                objs.append(
                    ListenerSession(
                        pk=s_id_uuid,
                        studio=studio,
                        ip_hash=s.get("ip_hash", ""),
                        user_agent=s.get("user_agent", ""),
                        client_type=s.get("client_type", ""),
                        country=s.get("country", ""),
                        region=s.get("region", ""),
                        city=s.get("city", ""),
                        lat=s.get("lat", None),
                        lon=s.get("lon", None),
                        total_bytes=int(s.get("total_bytes", 0) or 0),
                        ended_at=_parse_iso(s.get("ended_at")) or None,
                    )
                )

            if objs:
                existing_ids = set(
                    ListenerSession.objects.filter(
                        pk__in=[o.pk for o in objs]
                    ).values_list("pk", flat=True)
                )
                inserted = sum(1 for o in objs if o.pk not in existing_ids)
                updated = len(objs) - inserted

                ListenerSession.objects.bulk_create(
                    objs,
                    update_conflicts=True,
                    unique_fields=["id"],
                    update_fields=[
                        "ip_hash",
                        "user_agent",
                        "client_type",
                        "country",
                        "region",
                        "city",
                        "lat",
                        "lon",
                        "total_bytes",
                        "ended_at",
                        "last_seen",
                    ],
                )

            # Upsert ListenerStatBucket by unique (studio, interval, bucket_start)
            for b in buckets:
                interval = (b.get("interval", "")).upper()
                if interval not in {"MINUTE", "FIVE_MIN", "HOUR"}:
                    continue
                bucket_start = _parse_iso(b.get("bucket_start"))
                if not interval or not bucket_start:
                    continue

                active_peak = int(b.get("active_peak", 0))
                listener_minutes = int(b.get("listener_minutes", 0))
                countries = b.get("countries_json", {})

                obj, created = ListenerStatBucket.objects.update_or_create(
                    studio=studio,
                    interval=interval,
                    bucket_start=bucket_start,
                    defaults={
                        "active_peak": active_peak,
                        "listener_minutes": listener_minutes,
                        "countries_json": countries,
                    },
                )
                if not created:
                    changed = False
                    if active_peak > obj.active_peak:
                        obj.active_peak = active_peak
                        changed = True
                    if listener_minutes:
                        obj.listener_minutes = listener_minutes
                        changed = True
                    if changed:
                        obj.save(update_fields=["active_peak", "listener_minutes"])
                    if isinstance(countries, dict) and countries:
                        merged = dict(obj.countries_json or {})
                        for country, count in countries.items():
                            try:
                                merged[country] = int(merged.get(country, 0)) + int(
                                    count or 0
                                )
                            except Exception:
                                continue
                        obj.countries_json = merged
                        changed = True
                    if changed:
                        obj.save(
                            update_fields=[
                                "active_peak",
                                "listener_minutes",
                                "countries_json",
                            ]
                        )
                upserted += 1

        return inserted, updated, upserted

    inserted, updated, upserted = _run_with_deadlock_retry(_apply)

    return JsonResponse(
        {
            "ok": True,
            "studio": str(studio.pk),
            "inserted_sessions": inserted,
            "updated_sessions": updated,
            "upserted_buckets": upserted,
        },
        status=200,
    )
