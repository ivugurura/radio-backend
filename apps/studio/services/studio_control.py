import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

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
        print(
            f"radio-studio returned HTTP {exc.code} for studio {studio_slug}: {exc.reason}")
        raise StudioControlError(_error_message(exc)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"radio-studio unreachable for studio {studio_slug}: {exc}")
        raise StudioControlError(str(exc), unreachable=True) from exc


STUDIO_SYNC_TIMEOUT_SECONDS = 2


def request_studio_sync() -> bool:
    """Ask radio-studio to re-check the active studios now instead of at its
    next 5-minute poll. radio-studio reads the list from us itself, so this
    carries no state. Never raises: on failure the poll still applies the
    change. Returns whether radio-studio accepted the request."""
    base = (settings.STUDIO_INTERNAL_URL or "").rstrip("/")
    if not base:
        logger.info("studio sync not requested: STUDIO_INTERNAL_URL is not set")
        return False

    req = urllib.request.Request(
        f"{base}/internal/sync",
        method="POST",
        headers={"Authorization": f"Bearer {settings.STUDIO_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=STUDIO_SYNC_TIMEOUT_SECONDS):
            return True
    except Exception as exc:  # noqa: BLE001 - the poll is the fallback
        logger.warning(
            "studio sync request failed; radio-studio applies it at its next "
            "poll: %s",
            exc,
        )
        return False


def _error_message(exc: urllib.error.HTTPError) -> str:
    # radio-studio replies {"success": false, "error_msg": "..."}
    try:
        body = json.loads(exc.read() or b"{}")
        return body.get("error_msg") or exc.reason
    except (ValueError, AttributeError):
        return str(exc.reason)
