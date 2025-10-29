"""
Celery tasks for media processing.

This file registers start_pipeline_for_upload as a Celery task using
the shared_task decorator so it can be called with .delay() from the
GraphQL finalize mutation.

- Extract rich metadata (title, artist, album, year, genre) from input via ffprobe.
- Save extracted tags to Track fields if not already set or if they are empty.
- Preserve metadata during transcoding with ffmpeg -map_metadata 0.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.medias.models import Track
from apps.medias.services.paths import relpath_from_root, studio_paths

logger = logging.getLogger(__name__)


def resolve_bin(name: str, configured: str | None) -> str:
    """
    Resolve an executable path:
    - if configured is absolute and executable, use it
    - else try shutil.which(configured or name)
    - else raise a helpful error
    """
    cand = configured or name
    if os.path.isabs(cand) and os.access(cand, os.X_OK):
        return cand
    found = shutil.which(cand)
    if found:
        return found
    raise RuntimeError(
        f"{name} not found. Set {name.upper()}_PATH to an absolute path or install it and ensure it is on PATH."
    )


def ffprobe_json(ffprobe: str, in_path: Path) -> Dict:
    """Run ffprobe and return parsed JSON with format and streams info."""
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(in_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout or "{}")


def coerce_year_from_tags(tags: Dict[str, str]) -> Optional[int]:
    """
    Extract year from common tag keys: date, year, TDRC/TYER (ID3),
    e.g., '2023-05-12' => 2023; '2023' => 2023; '1999/01/01' => 1999
    """
    for key in ("date", "year", "tdrc", "tyer"):
        val = tags.get(key)
        if not val:
            continue
        # Keep only leading digits
        s = "".join(ch for ch in str(val) if ch.isdigit() or ch == "-")
        if len(s) >= 4 and s[:4].isdigit():
            try:
                y = int(s[:4])
                if 1900 <= y <= 2100:
                    return y
            except Exception:
                pass
    return None


def normalize_tag_key(k: str) -> str:
    """Lower-case, hyphen/underscore insensitive keys."""
    return k.strip().lower().replace("-", "_")


def extract_tags_from_probe(data: Dict) -> Tuple[float, Dict[str, str]]:
    """
    Returns (duration_seconds, tags_map)
    Prefers format.tags, falls back to first audio stream tags.
    """
    duration = 0.0
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except Exception:
        duration = 0.0

    tags: Dict[str, str] = {}
    fmt_tags = data.get("format", {}).get("tags") or {}
    for k, v in fmt_tags.items():
        tags[normalize_tag_key(k)] = str(v)

    if not tags:
        # fall back to first audio stream tags
        for st in data.get("streams", []):
            if st.get("codec_type") == "audio":
                st_tags = st.get("tags") or {}
                for k, v in st_tags.items():
                    tags[normalize_tag_key(k)] = str(v)
                break

    return duration, tags


@shared_task(bind=True, max_retries=2, soft_time_limit=60 * 60)
def start_pipeline_for_upload(self, track_id: str):
    """
    Worker entry point: normalize/transcode incoming upload and atomically publish
    to the studio library directory.

    Usage:
        start_pipeline_for_upload.delay(str(track.id))
    """
    try:
        track = Track.objects.select_related("studio", "upload_session").get(
            id=track_id
        )
    except Track.DoesNotExist:
        logger.error("start_pipeline_for_upload: track not found: %s", track_id)
        return

    studio = track.studio
    up = track.upload_session
    if not up or not up.temp_rel_path:
        logger.error(
            "start_pipeline_for_upload: missing upload session or temp path for track=%s",
            track_id,
        )
        track.state = Track.State.FAILED
        track.save(update_fields=["state", "updated_at"])
        return

    # Resolve ffmpeg/ffprobe robustly
    try:
        ffmpeg = resolve_bin("ffmpeg", getattr(settings, "FFMPEG_PATH", None))
        ffprobe = resolve_bin("ffprobe", getattr(settings, "FFPROBE_PATH", None))
    except RuntimeError as e:
        logger.error("Binary resolution error: %s", e)
        track.state = Track.State.FAILED
        track.error_message = str(e)[:4000]
        track.save(update_fields=["state", "error_message", "updated_at"])
        return

    target_kbps = getattr(studio, "default_bitrate_kbps", None) or getattr(
        settings, "DEFAULT_TARGET_BITRATE_KBPS", 128
    )

    paths = studio_paths(studio, target_kbps)
    work_in = Path(settings.RADIO_STUDIOS_ROOT) / up.temp_rel_path
    work_out = paths.processing / f"{track.id}.mp3"
    final_out = paths.library_mp3 / f"{track.id}.mp3"

    try:
        # Ensure dirs
        work_out.parent.mkdir(parents=True, exist_ok=True)
        final_out.parent.mkdir(parents=True, exist_ok=True)

        # Probe input (best effort)
        duration = 0.0
        probed_tags: Dict[str, str] = {}
        try:
            probe_json = ffprobe_json(ffprobe, work_in)
            duration, probed_tags = extract_tags_from_probe(probe_json)
        except Exception as e:
            logger.warning("ffprobe failed for %s: %s", work_in, e)

        # Map tags to Track fields (only fill if field is empty)
        # Common keys: title, artist, album, date/year, genre
        def pick(*keys: str) -> Optional[str]:
            for k in keys:
                v = probed_tags.get(k)
                if v:
                    return v
            return None

        new_title = pick("title", "tit2")
        new_artist = pick("artist", "tpe1", "album_artist", "tpe2")
        new_album = pick("album", "talb")
        new_genre = pick("genre", "tcon")
        new_year = coerce_year_from_tags(probed_tags)

        # Update preliminary metadata prior to processing (won't error if missing)
        dirty_fields = ["updated_at"]
        if new_title and not track.title:
            track.title = new_title
            dirty_fields.append("title")
        if new_artist and not track.artist:
            track.artist = new_artist
            dirty_fields.append("artist")
        if new_album and not track.album:
            track.album = new_album
            dirty_fields.append("album")
        if new_genre and not track.genre:
            track.genre = new_genre
            dirty_fields.append("genre")
        if new_year and not track.year:
            track.year = new_year
            dirty_fields.append("year")
        if dirty_fields:
            track.save(update_fields=dirty_fields)

        # Move to processing state
        track.state = Track.State.PROCESSING
        track.save(update_fields=["state", "updated_at"])

        # ffmpeg normalize + re-encode; preserve metadata with -map_metadata 0
        ff_cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(work_in),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-map_metadata",
            "0",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{target_kbps}k",
            str(work_out),
        ]
        logger.info("Running ffmpeg: %s", " ".join(ff_cmd))
        ff = subprocess.run(ff_cmd, capture_output=True, text=True)

        if ff.returncode != 0:
            logger.error(
                "ffmpeg failed for %s: code=%s stderr=%s",
                work_in,
                ff.returncode,
                ff.stderr[-4000:],
            )
            track.state = Track.State.FAILED
            track.error_message = (ff.stderr or "")[:4000]
            track.save(update_fields=["state", "error_message", "updated_at"])
            return

        # Atomic publish: replace is atomic on same filesystem
        work_out.replace(final_out)

        # Update Track
        track.duration_seconds = duration
        track.bitrate_kbps = target_kbps
        track.state = Track.State.READY
        track.processed_rel_path = relpath_from_root(final_out)
        track.updated_at = timezone.now()
        track.save(
            update_fields=[
                "duration_seconds",
                "bitrate_kbps",
                "state",
                "processed_rel_path",
                "updated_at",
            ]
        )

        # Cleanup incoming temp file
        try:
            work_in.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("cleanup incoming failed: %s", e)

        logger.info(
            "Processing finished for track %s (studio=%s)", track_id, studio.slug
        )

    except Exception as exc:
        # Retry with exponential backoff for transient errors
        logger.exception(
            "Unhandled error in start_pipeline_for_upload for %s", track_id
        )
        track.state = Track.State.FAILED
        track.error_message = str(exc)[:4096]
        track.save(update_fields=["state", "error_message", "updated_at"])
        try:
            # attempt retry (Celery will handle max_retries)
            raise self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error("Max retries exceeded for track %s", track_id)
        return
