from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List

from django.conf import settings
from django.db import transaction

from apps.medias.models import Track, UploadSession

logger = logging.getLogger(__name__)


def _track_files(track: Track) -> List[Path]:
    """
    Every file on disk that belongs to this track:
    - processed MP3 (processed_rel_path) and any other bitrate in library/mp3/*/
    - processing artifacts (processing/{track.id}.*)
    - waveform and artwork (waveform/{track.id}.*, artwork/{track.id}.*)
    - files recorded as TrackAssets (storage_key, relative to the studio dir)
    - the incoming partial upload (.part) of its upload session
    """
    root = Path(settings.RADIO_STUDIOS_ROOT)
    studio_root = root / track.studio.slug
    tid = str(track.id)

    files: List[Path] = []
    if track.processed_rel_path:
        files.append(studio_root / track.processed_rel_path)
    files += studio_root.glob(f"library/mp3/*/{tid}.mp3")
    for folder in ("processing", "waveform", "artwork"):
        files += (studio_root / folder).glob(f"{tid}.*")
    files += [
        studio_root / key
        for key in track.assets.values_list("storage_key", flat=True)
        if key
    ]
    up = track.upload_session
    if up and up.temp_rel_path:
        files.append(root / up.temp_rel_path)
    return files


def _unlink_all(files: Iterable[Path]) -> None:
    root = Path(settings.RADIO_STUDIOS_ROOT).resolve()
    for path in set(files):
        resolved = path.resolve()
        # Never follow a stored path outside the studios tree.
        if not resolved.is_relative_to(root):
            logger.warning("Refusing to delete %s: outside %s", resolved, root)
            continue
        try:
            resolved.unlink(missing_ok=True)
        except OSError as e:
            # A leftover file must not undo a delete the user already saw succeed.
            logger.warning("Could not delete %s: %s", resolved, e)


def hard_delete_track(track: Track) -> None:
    """
    Permanently remove a track: its files and its database rows.

    The DB cascade removes assets, transcode jobs, track tags and playlist
    items; play history keeps its rows with track set to NULL. Files are
    unlinked only after the transaction commits, so a rollback never leaves
    rows pointing at missing files.
    """
    files = _track_files(track)  # collect before the asset/session rows go
    up = track.upload_session
    track.hard_delete()
    if up:
        UploadSession.all_objects.filter(id=up.id).hard_delete()
    transaction.on_commit(lambda: _unlink_all(files))
