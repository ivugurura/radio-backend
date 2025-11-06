# Filesystem Layout (Local Disk)

Root: `/srv/radio`

Per studio:
- `/srv/radio/studios/{slug}/incoming/`      # partial uploads (.part)
- `/srv/radio/studios/{slug}/processing/`    # ffmpeg work dir
- `/srv/radio/studios/{slug}/library/mp3/{bitrate_kbps}/`  # finalized MP3s
- `/srv/radio/studios/{slug}/waveform/`      # optional JSON waveforms
- `/srv/radio/studios/{slug}/artwork/`       # cover art

Publishing is atomic:
- Write into `processing/uuid.tmp`
- On success, `os.rename()` to `library/mp3/{kbps}/{track_uuid}.mp3`

Go streamer:
- Configure `AUDIO_BASE_DIR=/srv/radio/studios` so studio `slug` matches Go studio ID.
- The Go service reads only from `library/mp3/{kbps}/` via its directory scan.
