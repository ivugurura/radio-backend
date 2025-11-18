from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.medias.models.track import Track

# If you use token auth, replace with your own decorator/middleware


@require_GET
def studio_playlist(request, studio_slug):
    limit = int(request.GET.get("limit", 50))
    # TODO: authN/authZ for studio_id, e.g., check API key/JWT scope

    # Fetch ordered tracks for studio_id from DB (ready-to-play order)
    # Example pseudo-ORM; replace with your models/ordering logic
    qs = Track.objects.filter(
        studio__slug=studio_slug, processed_rel_path__isnull=False
    ).order_by("created_at")[:limit]

    data = [
        {
            "id": str(t.id),
            "file": t.processed_rel_path,  # e.g., "uuid.mp3"
            "title": t.title,
            "artist": t.artist or "",
            "album": t.album or "",
            "duration_sec": t.duration_seconds or 0,
        }
        for t in qs
    ]

    return JsonResponse(data, safe=False)
