from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.medias.models.track import Track
from apps.studio.services.helpers import get_studio

# If you use token auth, replace with your own decorator/middleware


@require_GET
def studio_playlist(request, studio_slug):
    limit = int(request.GET.get("limit", 50))
    # TODO: authN/authZ for studio_id, e.g., check API key/JWT scope

    studio = get_studio(studio_slug)
    if studio is None:
        return JsonResponse([], safe=False)

    qs = Track.objects.filter(studio=studio, processed_rel_path__isnull=False).order_by(
        "created_at"
    )[:limit]

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
