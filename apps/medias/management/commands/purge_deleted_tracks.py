from django.core.management.base import BaseCommand
from django.db import transaction

from apps.medias.models import Track, UploadSession
from apps.medias.services.delete import hard_delete_track


class Command(BaseCommand):
    help = (
        "Permanently remove tracks and upload sessions that were soft-deleted "
        "before deletes became hard deletes, including their files on disk."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be removed.",
        )

    def handle(self, *args, dry_run=False, **options):
        tracks = Track.all_objects.filter(deleted_at__isnull=False).select_related(
            "studio", "upload_session"
        )
        sessions = UploadSession.all_objects.filter(deleted_at__isnull=False)
        self.stdout.write(
            f"{tracks.count()} soft-deleted track(s), "
            f"{sessions.count()} soft-deleted upload session(s)"
        )
        if dry_run:
            return

        purged = 0
        for track in tracks.iterator():
            # One transaction per track: files go only once its rows are gone.
            with transaction.atomic():
                hard_delete_track(track)
            purged += 1
        leftover = sessions.hard_delete()[0]
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {purged} track(s) and {leftover} other session row(s)"
            )
        )
