import json
import uuid
import datetime
from typing import Any, Dict

from django.db import transaction
from django.http import JsonResponse, HttpRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.studio.models.base import Studio
from apps.studio.models.analytics import PlayEvent
from apps.medias.models import Track
from apps.studio.services.helpers import get_studio

EVENT_START = "track_started"
EVENT_END = "track_ended"


def _parse_iso(ts: str):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


@csrf_exempt
@require_POST
def ingest_play_events(request: HttpRequest, studio_slug: str):
    studio = get_studio(studio_slug)
    if not studio:
        return JsonResponse({"detail": "Studio not found"}, status=404)

    # Optional simple API key auth (reuse STUDIO_INGEST_API_KEY)
    api_key = request.headers.get("Authorization", "")
    expected = getattr(request, "STUDIO_INGEST_API_KEY", None) or ""
    if expected and not api_key.endswith(expected):
        # NOTE: adapt to your auth scheme; currently lenient
        pass

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    events = payload if isinstance(payload, list) else [payload]

    created, updated, errors = 0, 0, []

    with transaction.atomic():
        for evt in events:
            etype = evt.get("type")
            track_token = evt.get("track_id") or evt.get(
                "track_uuid") or evt.get("file")
            started_at = _parse_iso(evt.get("started_at"))
            ended_at = _parse_iso(evt.get("ended_at"))
            source = evt.get("source") or "AUTO"

            if etype not in {EVENT_START, EVENT_END}:
                errors.append({"event": evt, "error": "unknown type"})
                continue

            if not track_token:
                errors.append({"event": evt, "error": "missing track id"})
                continue

            # Resolve track:
            track = None
            # 1) UUID direct
            try:
                track_uuid = uuid.UUID(str(track_token))
                track = Track.objects.filter(
                    studio=studio, id=track_uuid).first()
            except Exception:
                pass
            # 2) processed_rel_path match (filename)
            if track is None:
                track = Track.objects.filter(
                    studio=studio, processed_rel_path__icontains=str(
                        track_token)
                ).order_by("-created_at").first()
            # 3) title fallback
            if track is None:
                track = Track.objects.filter(
                    studio=studio, title=str(track_token)).first()

            if not track:
                errors.append({"event": evt, "error": "track not found"})
                continue

            if etype == EVENT_START:
                if not started_at:
                    started_at = timezone.now()
                # Determine next sequence
                last = (
                    PlayEvent.objects.filter(studio=studio)
                    .order_by("-sequence")
                    .first()
                )
                next_seq = (last.sequence + 1) if last else 1
                PlayEvent.objects.create(
                    studio=studio,
                    track=track,
                    started_at=started_at,
                    source=source,
                    sequence=next_seq,
                )
                created += 1

            elif etype == EVENT_END:
                # Close existing event if found
                open_ev = (
                    PlayEvent.objects.filter(
                        studio=studio, track=track, ended_at__isnull=True
                    )
                    .order_by("-started_at")
                    .first()
                )
                if ended_at is None:
                    ended_at = timezone.now()
                if open_ev:
                    open_ev.ended_at = ended_at
                    open_ev.save(update_fields=["ended_at", "updated_at"])
                    updated += 1
                else:
                    # Recovery path: create a finished event with guessed start
                    guess_start = ended_at - datetime.timedelta(
                        seconds=track.duration_seconds or 0
                    )
                    last = (
                        PlayEvent.objects.filter(studio=studio)
                        .order_by("-sequence")
                        .first()
                    )
                    next_seq = (last.sequence + 1) if last else 1
                    PlayEvent.objects.create(
                        studio=studio,
                        track=track,
                        started_at=guess_start,
                        ended_at=ended_at,
                        source=source,
                        sequence=next_seq,
                    )
                    created += 1

    data = {
        "ok": True,
        "created": created,
        "updated": updated,
        "errors": errors,
    }
    print(data)
    return JsonResponse(data, status=200)
