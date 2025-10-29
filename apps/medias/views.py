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
