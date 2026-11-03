import io
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.medias.models import Track, UploadSession
from apps.medias.services.delete import hard_delete_track
from apps.medias.services.paths import relpath_from_root, studio_paths
from apps.studio.models import Studio

CHUNK_SIZE = 1024 * 1024


class UploadConflictError(Exception): ...


class UploadRangeError(Exception): ...


def ensure_upload_token(upload: UploadSession) -> str:
    if not upload.upload_token:
        upload.upload_token = secrets.token_urlsafe(32)
        upload.save(update_fields=["upload_token"])
    return upload.upload_token


def init_upload(studio: Studio, upload: UploadSession) -> Path:
    paths = studio_paths(studio)
    temp_path = paths.incoming / f"{upload.id}.part"
    if not temp_path.exists():
        temp_path.touch()
    upload.temp_rel_path = relpath_from_root(temp_path)
    upload.bytes_received = temp_path.stat().st_size
    ensure_upload_token(upload)
    upload.save(update_fields=["temp_rel_path", "bytes_received", "updated_at"])

    return temp_path


def append_chunk(
    upload: UploadSession, start: int, end: int, total: int, body: io.BufferedReader
) -> int:
    if upload.finalized:
        raise UploadConflictError("Upload already finalized")
    if not upload.temp_rel_path:
        init_upload(upload.studio, upload)

    temp_abs = Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path
    temp_abs.parent.mkdir(parents=True, exist_ok=True)

    if start != upload.bytes_received and end != 0:
        raise UploadRangeError(
            f"Expected start={upload.bytes_received}, got start={start}"
        )

    to_write = end - start + 1
    remaining = to_write
    with open(temp_abs, "ab") as f:
        while remaining > 0:
            chunk = body.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)

    new_size = temp_abs.stat().st_size
    upload.bytes_received = new_size
    upload.size_bytes = total
    # BaseModel.updated_at is not auto_now; set it so stale-upload cleanup sees activity.
    upload.updated_at = timezone.now()
    upload.save(update_fields=["bytes_received", "size_bytes", "updated_at"])
    return new_size


def finalize_upload(upload: UploadSession) -> Path:
    if upload.finalized:
        return Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path
    temp_abs = Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path
    if not temp_abs.exists() or upload.size_bytes is None:
        raise UploadConflictError("Upload not complete")
    if not upload.temp_rel_path:
        raise UploadConflictError("Upload not initialized")
    if temp_abs.stat().st_size != upload.size_bytes:
        raise UploadConflictError("size mismatch")
    temp_abs = Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path

    upload.finalized = True
    upload.save(update_fields=["finalized", "updated_at"])
    return temp_abs


def _remove_part_file(upload: UploadSession) -> None:
    if not upload.temp_rel_path:
        return
    (Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path).unlink(missing_ok=True)


def cancel_upload(upload: UploadSession) -> None:
    """Discard an unfinished upload: its partial file, its track and the session."""
    if upload.finalized:
        raise UploadConflictError("Upload already finalized")
    tracks = Track.objects.select_related("studio", "upload_session").filter(
        upload_session=upload, state=Track.State.UPLOADING
    )
    for track in tracks:
        hard_delete_track(track)  # also removes the session and its .part file
    _remove_part_file(upload)
    UploadSession.all_objects.filter(id=upload.id).hard_delete()


def expire_stale_uploads(older_than: timedelta) -> int:
    """
    Fail uploads that stopped receiving chunks (tab closed, page refreshed,
    connection lost) so their tracks stop showing as UPLOADING forever.
    Returns the number of sessions expired.
    """
    cutoff = timezone.now() - older_than
    stale = UploadSession.objects.filter(finalized=False, updated_at__lt=cutoff)
    count = 0
    for upload in stale.iterator():
        _remove_part_file(upload)
        Track.objects.filter(upload_session=upload, state=Track.State.UPLOADING).update(
            state=Track.State.FAILED,
            error_message="Upload interrupted before it finished",
            updated_at=timezone.now(),
        )
        # The FAILED track stays visible; its upload_session becomes NULL.
        upload.hard_delete()
        count += 1
    return count


def sweep_orphan_part_files(older_than: timedelta) -> int:
    """
    Remove .part files in each studio's incoming/ that no live session owns,
    e.g. written by a chunk request that was still in flight during a cancel.
    """
    cutoff = (timezone.now() - older_than).timestamp()
    root = Path(settings.RADIO_STUDIOS_ROOT)
    owned = set(
        UploadSession.objects.exclude(temp_rel_path="").values_list(
            "temp_rel_path", flat=True
        )
    )
    removed = 0
    for part in root.glob("*/incoming/*.part"):
        if str(part.relative_to(root)) in owned:
            continue
        try:
            if part.stat().st_mtime < cutoff:
                part.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed
