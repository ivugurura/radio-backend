from __future__ import annotations
from pathlib import Path
from typing import Optional
from django.conf import settings
from apps.medias.models import Track
from apps.medias.services.paths import studio_paths

def _safe_unlink(p: Optional[Path]) -> None:
    try:
        if p and p.exists():
            p.unlink()
    except Exception:
        # Intentionally ignore file removal errors, we don't want to block deletion
        pass

def delete_track_files(track: Track) -> None:
    """
    Remove any files associated with this track from local disk:
    - processed file in library (processed_rel_path)
    - incoming partial upload (.part)
    - processing artifact (processing/{track.id}.mp3)
    """
    base = Path(settings.RADIO_STUDIOS_ROOT)

    # Processed file
    if track.processed_rel_path:
        _safe_unlink(base / track.processed_rel_path)

    # Incoming temp (.part)
    up = getattr(track, "upload_session", None)
    if up and up.temp_rel_path:
        _safe_unlink(base / up.temp_rel_path)

    # Processing artifact – try to infer path using bitrate (fallback to settings)
    target_kbps = track.bitrate_kbps or getattr(settings, "DEFAULT_TARGET_BITRATE_KBPS", 128)
    paths = studio_paths(track.studio, target_kbps)
    _safe_unlink(paths.processing / f"{track.id}.mp3")
