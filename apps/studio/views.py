from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from apps.medias.models.track import Track
# If you use token auth, replace with your own decorator/middleware


@require_GET
def studio_playlist(request, studio_id):
    limit = int(request.GET.get("limit", 50))
    # TODO: authN/authZ for studio_id, e.g., check API key/JWT scope

    # Fetch ordered tracks for studio_id from DB (ready-to-play order)
    # Example pseudo-ORM; replace with your models/ordering logic
    qs = (Track.objects
          .filter(studio_id=studio_id, is_ready=True)
          .order_by("created_at")[:limit])

    data = [{
        "id": str(t.id),
        "path": t.processed_rel_path,  # e.g., "uuid.mp3"
        "title": t.title,
        "artist": t.artist or "",
        "album": t.album or "",
        "duration_sec": t.duration_sec or 0,
    } for t in qs]

    return JsonResponse(data, safe=False)
