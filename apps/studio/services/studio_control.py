import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

STUDIO_CONTROL_TIMEOUT_SECONDS = 5


class StudioControlError(Exception):
    """radio-studio refused a control action or could not be reached."""

    def __init__(self, message: str, *, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


def skip_track(studio_slug: str) -> None:
    """Ask radio-studio's AutoDJ to skip the track it is currently playing."""
    base = settings.STUDIO_INTERNAL_URL.rstrip("/")
    url = f"{base}/studios/{urllib.parse.quote(studio_slug, safe='')}/skip"

    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Authorization": f"Bearer {settings.STUDIO_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=STUDIO_CONTROL_TIMEOUT_SECONDS):
            print(f"Successfully requested skip for studio {studio_slug}")
            return
    except urllib.error.HTTPError as exc:
        raise StudioControlError(_error_message(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StudioControlError(str(exc), unreachable=True) from exc


def _error_message(exc: urllib.error.HTTPError) -> str:
    # radio-studio replies {"success": false, "error_msg": "..."}
    try:
        body = json.loads(exc.read() or b"{}")
        return body.get("error_msg") or exc.reason
    except (ValueError, AttributeError):
        return str(exc.reason)
