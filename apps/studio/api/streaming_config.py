from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.studio.services.helpers import (
    get_or_create_streaming_credential,
    get_studio,
    is_studio_server_request,
)


@csrf_exempt
@require_GET
def streaming_config(request: HttpRequest, studio_slug: str) -> JsonResponse:
    """Serves the live-ingest credentials radio-studio authenticates encoders against."""
    if not is_studio_server_request(request):
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
            # Sent to listeners as the stream's icy-name/icy-description.
            "station_name": studio.display_name,
            "station_description": studio.description,
        },
        status=200,
    )
