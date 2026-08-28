from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.studio.services.helpers import get_or_create_streaming_credential, get_studio


def _bearer_token(req: HttpRequest) -> str:
    auth_header = req.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return ""


@csrf_exempt
@require_GET
def streaming_config(request: HttpRequest, studio_slug: str) -> JsonResponse:
    """Serves the live-ingest credentials radio-studio authenticates encoders against."""
    token = _bearer_token(request)
    expected = getattr(settings, "STUDIO_TOKEN", "")
    if not token or not expected or token != expected:
        return JsonResponse({"message": "Not authorized"}, status=401)

    studio = get_studio(studio_slug)
    if not studio:
        return JsonResponse({"message": "Studio not found"}, status=404)

    credential = get_or_create_streaming_credential(studio)
    return JsonResponse(
        {
            "username": credential.username,
            "password": credential.get_password(),
            "bitrate_kbps": studio.default_br_kbps,
            "sample_rate_hz": studio.default_sr_hz,
            "channels": studio.default_ch,
        },
        status=200,
    )
