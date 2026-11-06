from django.core.management.base import BaseCommand

from apps.medias.models import Track
from apps.medias.services.assets import processed_mp3_path, record_mp3_asset


class Command(BaseCommand):
    help = (
        "Record the on-disk size of every processed track as a NORMALIZED_MP3 "
        "TrackAsset, so the dashboard disk usage counts tracks whose upload "
        "sessions are gone."
    )

    def add_arguments(self, parser):
        parser.add_argument('--studio', help='Only this studio slug.')
        parser.add_argument(
            '--dry-run', action='store_true', help='Only report what would change.'
        )

    def handle(self, *args, studio=None, dry_run=False, **options):
        tracks = Track.objects.select_related('studio').exclude(processed_rel_path='')
        if studio:
            tracks = tracks.filter(studio__slug=studio)

        recorded, missing, total_bytes = 0, [], 0
        for track in tracks.iterator():
            path = processed_mp3_path(track)
            if not path.is_file():
                missing.append(f'{track.studio.slug}/{track.processed_rel_path}')
                continue
            size = path.stat().st_size
            if not dry_run:
                record_mp3_asset(track)
            recorded += 1
            total_bytes += size

        verb = 'Would record' if dry_run else 'Recorded'
        self.stdout.write(
            self.style.SUCCESS(
                f'{verb} {recorded} track(s), {total_bytes / (1024**3):.3f} GB'
            )
        )
        if missing:
            self.stdout.write(self.style.WARNING(f'{len(missing)} file(s) missing:'))
            for m in missing:
                self.stdout.write(f'  {m}')
