from django.http import FileResponse, Http404
from apps.medias.models.track import Track
from apps.studio.models import Studio
from django.conf import settings
from pathlib import Path
from django.views.decorators.http import require_GET
import re

from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from apps.medias.models import UploadSession
from apps.medias.services.upload import append_chunk

CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


@csrf_exempt
def upload_chunk_view(request, upload_id):
    print(request.method)
    if request.method != "PUT":
        return HttpResponseNotAllowed(["PUT"])

    upload = get_object_or_404(UploadSession, id=upload_id, finalized=False)

    token = request.headers.get("X-Upload-Token", "")
    if not token or token != upload.upload_token:
        return HttpResponseForbidden("Invalid upload token")

    cr = request.headers.get("Content-Range", "")
    if not cr:
        return HttpResponseBadRequest("Missing Content-Range header")
    m = CONTENT_RANGE_RE.match(cr)
    if not m:
        return HttpResponseBadRequest("Invalid Content-Range header format")
    start, end, total = map(int, m.groups())

    size = append_chunk(upload, start, end, total, request)
    return HttpResponse({"received": size})


@require_GET
def serve_track(request, studio_slug, track_id):
    """Serve MP3 files for streaming"""
    try:
        track = Track.objects.get(id=track_id, studio__slug=studio_slug)
        file_path = Path(settings.RADIO_STUDIOS_ROOT) / \
            studio_slug / track.processed_rel_path
        print("Serving track from:", file_path)
        print(file_path)
        if not file_path.exists() or not file_path.is_file():
            raise Http404("Track not found")

        # Serve with proper headers for audio streaming
        response = FileResponse(
            open(file_path, 'rb'),
            content_type='audio/mpeg'
        )
        response['Accept-Ranges'] = 'bytes'
        response['Content-Disposition'] = f'inline; filename="{track.title}"'

        return response
    except Studio.DoesNotExist:
        raise Http404("Studio not found")
