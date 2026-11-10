from django.db import migrations

# Studios are addressed by the UI language code they serve.
SLUG_RENAMES = {
    "reformation-rw": "rw",
}


def _rename(apps, renames: dict[str, str]):
    Studio = apps.get_model("studio", "Studio")
    UploadSession = apps.get_model("medias", "UploadSession")

    for old, new in renames.items():
        # all_objects would be nicer, but historical models only get the default
        # manager; filter on slug alone so soft-deleted rows are renamed too.
        studio = Studio._base_manager.filter(slug=old).first()
        if studio is None:
            continue
        if Studio._base_manager.filter(slug=new).exists():
            raise RuntimeError(f"Cannot rename studio {old!r}: {new!r} already exists")
        studio.slug = new
        studio.save(update_fields=["slug"])

        # In-flight uploads store their temp path relative to RADIO_STUDIOS_ROOT,
        # so it starts with the slug. Track.processed_rel_path does not.
        prefix = f"{old}/"
        for up in UploadSession._base_manager.filter(temp_rel_path__startswith=prefix):
            up.temp_rel_path = f"{new}/{up.temp_rel_path[len(prefix):]}"
            up.save(update_fields=["temp_rel_path"])


def forwards(apps, schema_editor):
    _rename(apps, SLUG_RENAMES)


def backwards(apps, schema_editor):
    _rename(apps, {new: old for old, new in SLUG_RENAMES.items()})


class Migration(migrations.Migration):
    """Rename studio slugs to language codes.

    The media folders under RADIO_STUDIOS_ROOT (and radio-studio's AUDIO_DIR)
    are named after the slug and must be renamed on disk at deploy time.
    """

    dependencies = [
        ("medias", "0004_track_live_content_hash_unique"),
        ("studio", "0008_listener_session_key_and_started_at"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
