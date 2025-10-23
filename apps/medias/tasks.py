from __future__ import annotations
import json
import subprocess
from pathlib import Path
from django.conf import settings
from apps.medias.models import Track
from apps.medias.services.paths import studio_paths, relpath_from_root

@shared_task(bind=True, max_retries=2)
def start_pipeline_for_upload(self, track_id: str):
    track = Track.objects.select_related("studio","upload_session").get(id=track_id)
    studio = track.studio
    up = track.upload_session
    if not up or not up.temp_rel_path:
        track.state = Track.State.FAILED
        track.save(update_fields=["state","updated_at"])
        return

    target_kbps = studio.default_bitrate_kbps if hasattr(studio, "default_bitrate_kbps") and studio.default_bitrate_kbps else getattr(settings, "DEFAULT_TARGET_BITRATE_KBPS", 128)
    paths = studio_paths(studio, target_kbps)
    work_in = Path(settings.RADIO_STUDIOS_ROOT) / up.temp_rel_path
    work_out = paths.processing / f"{track.id}.mp3"
    final_out = paths.library_mp3 / f"{track.id}.mp3"
    work_out.parent.mkdir(parents=True, exist_ok=True)
    final_out.parent.mkdir(parents=True, exist_ok=True)

    # Probe duration/bitrate best-effort
    duration = 0.0
    try:
        probe = subprocess.run(
            [getattr(settings, "FFPROBE_PATH", "ffprobe"), "-v", "error", "-show_entries", "format=duration,bit_rate", "-of", "json", str(work_in)],
            capture_output=True, text=True, check=True
        )
        info = json.loads(probe.stdout or "{}")
        duration = float(info.get("format",{}).get("duration", 0.0) or 0.0)
    except Exception:
        pass

    # Transcode + loudness normalize
    track.state = Track.State.PROCESSING
    track.save(update_fields=["state","updated_at"])
    ff = subprocess.run(
        [
            getattr(settings, "FFMPEG_PATH", "ffmpeg"), "-y", "-i", str(work_in),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "libmp3lame", "-b:a", f"{target_kbps}k",
            str(work_out),
        ],
        capture_output=True, text=True
    )
    if ff.returncode != 0:
        track.state = Track.State.FAILED
        track.save(update_fields=["state","updated_at"])
        return

    # Atomic publish
    work_out.replace(final_out)
    track.duration_seconds = duration
    track.bitrate_kbps = target_kbps
    track.state = Track.State.READY
    track.processed_rel_path = relpath_from_root(final_out)
    track.save(update_fields=["duration_seconds","bitrate_kbps","state","processed_rel_path","updated_at"])

    # Cleanup temp
    try:
        work_in.unlink(missing_ok=True)
    except Exception:
        pass
