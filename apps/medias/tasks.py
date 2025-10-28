"""
Celery tasks for media processing.

This file registers start_pipeline_for_upload as a Celery task using
the shared_task decorator so it can be called with .delay() from the
GraphQL finalize mutation.

It expects config settings:
- RADIO_STUDIOS_ROOT
- FFMPEG_PATH (optional)
- FFPROBE_PATH (optional)
- DEFAULT_TARGET_BITRATE_KBPS (optional)

FFmpeg/ffprobe must be installed on the host and available in PATH or configured via settings.
"""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.medias.models import Track
from apps.medias.services.paths import studio_paths, relpath_from_root

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, soft_time_limit=60 * 60)
def start_pipeline_for_upload(self, track_id: str):
    """
    Worker entry point: normalize/transcode incoming upload and atomically publish
    to the studio library directory.

    Usage:
        start_pipeline_for_upload.delay(str(track.id))
    """
    try:
        track = Track.objects.select_related("studio", "upload_session").get(id=track_id)
    except Track.DoesNotExist:
        logger.error("start_pipeline_for_upload: track not found: %s", track_id)
        return

    studio = track.studio
    up = track.upload_session
    if not up or not up.temp_rel_path:
        logger.error("start_pipeline_for_upload: missing upload session or temp path for track=%s", track_id)
        track.state = Track.State.FAILED
        track.save(update_fields=["state", "updated_at"])
        return

    # resolution of ffmpeg/ffprobe and bitrate
    ffmpeg = getattr(settings, "FFMPEG_PATH", "ffmpeg")
    ffprobe = getattr(settings, "FFPROBE_PATH", "ffprobe")
    target_kbps = getattr(studio, "default_bitrate_kbps", None) or getattr(settings, "DEFAULT_TARGET_BITRATE_KBPS", 128)

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
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration,bit_rate", "-of", "json", str(work_in)],
                capture_output=True,
                text=True,
                check=True,
            )
            info = json.loads(probe.stdout or "{}")
            duration = float(info.get("format", {}).get("duration", 0.0) or 0.0)
        except Exception as e:
            logger.warning("ffprobe failed for %s: %s", work_in, e)

        # Move to processing state
        track.state = Track.State.PROCESSING
        track.save(update_fields=["state", "updated_at"])

        # Run ffmpeg: loudness normalize + encode to target CBR MP3
        ff_cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(work_in),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{target_kbps}k",
            str(work_out),
        ]
        logger.info("Running ffmpeg: %s", " ".join(ff_cmd))
        ff = subprocess.run(ff_cmd, capture_output=True, text=True)

        if ff.returncode != 0:
            logger.error("ffmpeg failed for %s: code=%s stderr=%s", work_in, ff.returncode, ff.stderr[-4000:])
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
        track.save(update_fields=["duration_seconds", "bitrate_kbps", "state", "processed_rel_path", "updated_at"])

        # Cleanup incoming temp file
        try:
            work_in.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("cleanup incoming failed: %s", e)

        logger.info("Processing finished for track %s (studio=%s)", track_id, studio.slug)

    except Exception as exc:
        # Retry with exponential backoff for transient errors
        logger.exception("Unhandled error in start_pipeline_for_upload for %s", track_id)
        track.state = Track.State.FAILED
        track.error_message = str(exc)[:4096]
        track.save(update_fields=["state", "error_message", "updated_at"])
        try:
            # attempt retry (Celery will handle max_retries)
            raise self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error("Max retries exceeded for track %s", track_id)
        return
