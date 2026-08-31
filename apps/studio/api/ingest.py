import datetime
import json
import random
import time
import uuid

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
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

    now = timezone.now()
    GRACE_PERIOD = datetime.timedelta(
        seconds=20
    )  # noqa: F841 (reserved for future use)

    def _apply():
        inserted = 0
        updated = 0
        upserted = 0

        with transaction.atomic():
            # Serialize concurrent ingests for this studio. A studio flushes its
            # entire listener roster every few seconds; under load one request
            # can still be running when the next arrives, and the two would lock
            # the same listener_sessions rows and deadlock. This transaction-
            # scoped advisory lock makes them queue instead. Released on commit.
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    [f"listener_ingest:{studio.pk}"],
                )

            # Upsert ListenerSession by explicit UUID (client-provided)
            for s in sessions:
                s_id = s.get("id")
                if not s_id:
                    continue
                try:
                    s_id_uuid = uuid.UUID(s_id)
                except Exception:
                    s_id_uuid = uuid.uuid4()

                started_at = _parse_iso(s.get("started_at")) or None
                ended_at = _parse_iso(s.get("ended_at")) or None

                defaults = {
                    "studio": studio,
                    "ip_hash": s.get("ip_hash", ""),
                    "user_agent": s.get("user_agent", ""),
                    "client_type": s.get("client_type", ""),
                    "country": s.get("country", ""),
                    "region": s.get("region", ""),
                    "city": s.get("city", ""),
                    "lat": s.get("lat", None),
                    "lon": s.get("lon", None),
                    "total_bytes": int(s.get("total_bytes", 0)),
                }

                if started_at:
                    defaults["started_at"] = started_at
                if ended_at:
                    defaults["ended_at"] = ended_at
                session, created = ListenerSession.objects.update_or_create(
                    pk=s_id_uuid, defaults=defaults
                )
                if created:
                    inserted += 1
                else:
                    changed = False
                    for k, v in defaults.items():
                        if k == "total_bytes":
                            new_val = max(getattr(session, k) or 0, int(v or 0))
                        else:
                            new_val = v
                        if getattr(session, k) != new_val:
                            setattr(session, k, new_val)
                            changed = True
                    if changed:
                        session.save(update_fields=list(defaults.keys()))
                    updated += 1

                # Always reflesh last_seen to now on any heartbeat
                ListenerSession.objects.filter(pk=session.pk).update(last_seen=now)

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
