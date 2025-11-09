import json
import uuid

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse, HttpRequest
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.studio.models import Studio, ListenerSession, ListenerStatBucket


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

def _parse_iso(dt_str:str):
    if dt_str is None:
        return None
    return parse_datetime(dt_str)

def _bearer_token(req:HttpRequest)->str:
    auth_header = req.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""

def _get_studio(studio_slug_or_id:str):
    try:
        if len(studio_slug_or_id) == 36:  # Assuming UUID length
            studio = Studio.objects.get(id=studio_slug_or_id)
        else:
            studio = Studio.objects.get(slug=studio_slug_or_id)
        return studio
    except Studio.DoesNotExist:
        return None

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
    print(token)
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
    studio = _get_studio(studio_slug)
    if not studio:
        return server_response("Studio not found", status_code=404)

    sessions = payload.get("sessions") or []
    buckets = payload.get("buckets") or []

    inserted_sessions = 0
    updated_sessions = 0
    upserted_buckets = 0

    with transaction.atomic():
        # Upsert ListenerSession by explicit UUID (client-provided)
        for s in sessions:
            s_id = s.get("id")
            if not s_id:
                continue
            try:
                s_id_uuid = uuid.UUID(s_id)
            except Exception:
                s_id_uuid = uuid.uuid4

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
            session, created = ListenerSession.objects.update_or_create(pk=s_id_uuid, defaults=defaults)
            if created:
                inserted_sessions += 1
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
                    session.save()
                    updated_sessions += 1

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
                studio=studio, interval=interval, bucket_start=bucket_start,
                defaults={
                    "active_peak": active_peak,
                    "listener_minutes": listener_minutes,
                    "countries_json": countries,
                }
            )
            if not created:
                updated = False
                if active_peak > obj.active_peak:
                    obj.active_peak = active_peak
                    updated = True
                if listener_minutes:
                    obj.listener_minutes = listener_minutes
                    updated = True
                if isinstance(countries, dict) and countries:
                    merged = dict(obj.countries_json or {})
                    for country, count in countries.items():
                        try:
                            merged[country] = int(merged.get(country, 0)) + int(count or 0)
                        except Exception:
                            continue
                    obj.countries_json = merged
                    updated = True
                if updated:
                    obj.save(update_fields=["active_peak", "listener_minutes", "countries_json"])
            upserted_buckets += 1

    return JsonResponse({"ok":True, "studio":str(studio.pk), "inserted_sessions": inserted_sessions, "updated_sessions": updated_sessions, "upserted_buckets": upserted_buckets}, status=200)
