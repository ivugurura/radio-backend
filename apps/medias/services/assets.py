from __future__ import annotations

from pathlib import Path
from typing import Optional

from django.conf import settings

from apps.medias.models import Track, TrackAsset


def processed_mp3_path(track: Track) -> Optional[Path]:
    if not track.processed_rel_path:
        return None
    studio_root = Path(settings.RADIO_STUDIOS_ROOT) / track.studio.slug
    return studio_root / track.processed_rel_path


def record_mp3_asset(track: Track) -> Optional[TrackAsset]:
    """
    Create or refresh the NORMALIZED_MP3 asset row for a processed track,
    with size_bytes read from the file on disk. Returns None when the track
    has no processed file or the file is missing.
    """
    path = processed_mp3_path(track)
    if path is None or not path.is_file():
        return None
    asset, _ = TrackAsset.objects.update_or_create(
        track=track,
        asset_type=TrackAsset.AssetType.NORMALIZED_MP3,
        defaults={
            'storage_key': track.processed_rel_path,
            'size_bytes': path.stat().st_size,
            'mime_type': 'audio/mpeg',
        },
    )
    return asset
