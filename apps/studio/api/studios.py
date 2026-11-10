from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from apps.studio.models import Studio
from apps.studio.services.helpers import is_studio_server_request


@csrf_exempt
@require_GET
def list_studios(request: HttpRequest) -> JsonResponse:
    """Lists the active studios radio-studio should register and stream."""
    if not is_studio_server_request(request):
        return JsonResponse({"message": "Not authorized"}, status=401)

    studios = Studio.objects.filter(is_active=True).order_by("slug")
    return JsonResponse(
        [
            {
                "slug": s.slug,
                "display_name": s.display_name,
                "bitrate_kbps": s.default_br_kbps,
                "sample_rate_hz": s.default_sr_hz,
                "channels": s.default_ch,
            }
            for s in studios
        ],
        safe=False,
    )
