import io
import secrets
from pathlib import Path

from apps.medias.models import UploadSession
from apps.medias.services.paths import studio_paths, relpath_from_root
from apps.studio.models import Studio
from config import settings

CHUNK_SIZE = 1024 * 1024

class UploadConflictError(Exception): ...
class UploadRangeError(Exception): ...

def ensure_upload_token(upload: UploadSession) -> str:
    if not upload.upload_token:
        upload.upload_token = secrets.token_urlsafe(32)
        upload.save(update_fields=["upload_token"])
    return upload.upload_token

def init_upload(studio: Studio, upload:UploadSession) -> Path:
    paths = studio_paths(studio)
    temp_path = paths.incoming / f"{upload.id}.part"
    if not  temp_path.exists():
        temp_path.touch()
    upload.temp_rel_path = relpath_from_root(temp_path)
    upload.bytes_received = temp_path.stat().st_size
    ensure_upload_token(upload)
    upload.save(update_fields=["temp_rel_path", "bytes_received", "updated_at"])

    return temp_path

def append_chunk(upload: UploadSession, start:int, end: int, total:int, body:io.BufferedReader) -> int:
    if upload.finalized:
        raise UploadConflictError("Upload already finalized")
    if not upload.temp_rel_path:
        init_upload(upload.studio, upload)

    temp_abs = Path(settings.RADIO_STUDIOS_ROOT) / upload.temp_rel_path
    temp_abs.parent.mkdir(parents=True, exist_ok=True)

    if start != upload.bytes_received and end != 0:
        raise UploadRangeError(f"Expected start={upload.bytes_received}, got start={start}")

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
