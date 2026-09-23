import re
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.common.translations import translate
from apps.medias.models import UploadSession
from apps.medias.models.track import Track
from apps.medias.services.upload import append_chunk

CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


@csrf_exempt
def upload_chunk_view(request, upload_id):
    if request.method != "PUT":
        return HttpResponseNotAllowed(["PUT"])

    upload = get_object_or_404(UploadSession, id=upload_id, finalized=False)

    token = request.headers.get("X-Upload-Token", "")
    if not token or token != upload.upload_token:
        return HttpResponseForbidden(translate("medias.invalid_upload_token"))

    cr = request.headers.get("Content-Range", "")
    if not cr:
        return HttpResponseBadRequest(translate("medias.missing_content_range"))
    m = CONTENT_RANGE_RE.match(cr)
    if not m:
        return HttpResponseBadRequest(translate("medias.invalid_content_range"))
    start, end, total = map(int, m.groups())

    size = append_chunk(upload, start, end, total, request)
    return HttpResponse({"received": size})


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
STREAM_BLOCK_SIZE = 64 * 1024


def _iter_file_range(path: Path, start: int, length: int):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(STREAM_BLOCK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@require_GET
def serve_track(request, studio_slug, track_id):
    """Serve a processed MP3, honouring HTTP Range so browsers can seek."""
    track = (
        Track.objects.filter(
            id=track_id, studio__slug=studio_slug, state=Track.State.READY
        )
        .exclude(processed_rel_path="")
        .first()
    )
    if track is None:
        raise Http404(translate("medias.track_not_found"))

    studio_root = (Path(settings.RADIO_STUDIOS_ROOT) / studio_slug).resolve()
    file_path = (studio_root / track.processed_rel_path).resolve()
    if not file_path.is_relative_to(studio_root) or not file_path.is_file():
        raise Http404(translate("medias.track_not_found"))

    size = file_path.stat().st_size
    filename = quote(f"{track.title or track.id}.mp3")
    range_header = request.headers.get("Range", "")
    match = RANGE_RE.fullmatch(range_header.strip()) if range_header else None

    if match and (match.group(1) or match.group(2)):
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:  # suffix range: last N bytes
            start = max(0, size - int(last))
            end = size - 1
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1
        response = StreamingHttpResponse(
            _iter_file_range(file_path, start, length),
            status=206,
            content_type="audio/mpeg",
        )
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)
    else:
        response = FileResponse(open(file_path, "rb"), content_type="audio/mpeg")
        response["Content-Length"] = str(size)

    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f"inline; filename*=UTF-8''{filename}"
    response["Cache-Control"] = "private, max-age=3600"
    return response
