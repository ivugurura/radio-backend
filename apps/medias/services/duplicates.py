from __future__ import annotations

from decimal import Decimal
from typing import Optional

from apps.medias.models import Track
from apps.studio.models import Studio

# Same song re-encoded or re-tagged rarely drifts more than this in length.
DURATION_TOLERANCE_SECONDS = Decimal("2")


def find_exact_duplicate(studio: Studio, content_hash: str) -> Optional[Track]:
    """Live track in this studio whose file has the same SHA-256 (level 1)."""
    return Track.objects.filter(studio=studio, content_hash=content_hash).first()


def find_metadata_duplicate(track: Track, duration: float) -> Optional[Track]:
    """
    Earliest track in the studio with the same title and artist and a length
    within DURATION_TOLERANCE_SECONDS (level 2). This only flags: a live and a
    studio take of one song can match, so staff decide what to keep.
    """
    if not track.title or not track.artist or not duration:
        return None
    length = Decimal(str(duration))
    return (
        Track.objects.filter(
            studio_id=track.studio_id,
            title__iexact=track.title,
            artist__iexact=track.artist,
            duration_seconds__gte=length - DURATION_TOLERANCE_SECONDS,
            duration_seconds__lte=length + DURATION_TOLERANCE_SECONDS,
        )
        .exclude(id=track.id)
        .exclude(state__in=[Track.State.FAILED, Track.State.UPLOADING])
        .order_by("created_at")
        .first()
    )
