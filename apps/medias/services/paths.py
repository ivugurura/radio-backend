import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.studio.models import Studio


@dataclass(frozen=True)
class StudioPaths:
    root: Path
    incoming: Path
    processing: Path
    library_mp3: Path
    waveform: Path
    artwork: Path

def studio_paths(studio: Studio, bitrate_kbps:int|None=None) -> StudioPaths:
    root = Path(settings.RADIO_STUDIOS_ROOT) / studio.slug
    incoming = root / 'incoming'
    processing = root / 'processing'
    library_mp3 = root / 'library' / 'mp3' / str(bitrate_kbps or settings.DEFAULT_TARGET_BITRATE_KBPS)
    waveform = root / 'waveform'
    artwork = root / 'artwork'
    for p in (incoming, processing, library_mp3, waveform, artwork):
        p.mkdir(parents=True, exist_ok=True)
    return StudioPaths(root, incoming, processing, library_mp3, waveform, artwork)

def relpath_from_root(p: Path) -> str:
    root = Path(settings.RADIO_STUDIOS_ROOT)
    return str(Path(os.path.relpath(p, root)))
