from django.db import migrations


class Migration(migrations.Migration):
    """One-time pre-launch reset, applied once per database by `migrate`.

    Keeps studios, audio (tracks, assets, tags) and users with their access.
    Removes all other data. It cannot be reversed: back up before applying.
    """

    dependencies = [
        ("admin", "__latest__"),
        ("chat", "0001_initial"),
        (
            "medias",
            "0003_rename_processed_storage_key_track_processed_rel_path_and_more",
        ),
        ("refresh_token", "__latest__"),
        ("sessions", "__latest__"),
        ("studio", "0006_studio_default_ch_studio_default_sr_hz_and_more"),
        ("users", "0002_user_timezone"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Detach tracks from the upload rows deleted below.
                "UPDATE tracks SET upload_session_id = NULL "
                "WHERE upload_session_id IS NOT NULL",
                # No CASCADE on purpose: it would follow tracks.upload_session_id
                # and empty tracks.
                """
                TRUNCATE TABLE
                    chat_messages,
                    chat_mutes,
                    play_events,
                    listener_sessions,
                    listener_stat_buckets,
                    live_sessions,
                    show_slots,
                    scheduled_shows,
                    playlist_items,
                    playlists,
                    rotation_rules,
                    streaming_credentials,
                    transcode_jobs,
                    refresh_token_refreshtoken,
                    django_admin_log,
                    django_session
                """,
                # DELETE, not TRUNCATE: tracks still has a foreign key to this table.
                "DELETE FROM upload_sessions",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
