import logging
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, router, transaction
from django.db.models.deletion import Collector

from apps.studio.models import Studio
from apps.studio.services.helpers import LEGACY_STUDIO_SLUGS

logger = logging.getLogger(__name__)


def find_studio(studio_id: str) -> Studio | None:
    """Like get_studio(), but also finds soft-deleted studios."""
    slug = LEGACY_STUDIO_SLUGS.get(studio_id, studio_id)
    studio = Studio.all_objects.filter(slug=slug).first()
    if studio:
        return studio
    try:
        pk = uuid.UUID(studio_id)
    except ValueError:
        return None
    return Studio.all_objects.filter(pk=pk).first()


def studio_dir(studio: Studio) -> Path:
    """The studio's media folder, refusing anything outside the studios tree."""
    root = Path(settings.RADIO_STUDIOS_ROOT).resolve()
    path = (root / studio.slug).resolve()
    if not studio.slug or path == root or not path.is_relative_to(root):
        raise CommandError(f'Refusing to delete {path}: not a studio folder.')
    return path


def cascade_counts(studio: Studio) -> dict[str, int]:
    """Rows that hard-deleting the studio removes, per model. The collector
    uses each model's base manager, so soft-deleted rows are counted too."""
    collector = Collector(using=router.db_for_write(Studio) or DEFAULT_DB_ALIAS)
    collector.collect([studio])
    counts: dict[str, int] = {}
    for model, objs in collector.data.items():
        counts[model._meta.label] = counts.get(model._meta.label, 0) + len(objs)
    for qs in collector.fast_deletes:
        label = qs.model._meta.label
        counts[label] = counts.get(label, 0) + qs.count()
    return {label: n for label, n in sorted(counts.items()) if n}


class Command(BaseCommand):
    help = (
        'Permanently delete a studio and everything in it: tracks, uploads, '
        'playlists, schedule, members, streaming credentials, analytics, chat '
        'and its media folder. The studio must be deactivated first. This '
        'cannot be undone.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'studio', help='Studio slug (or legacy slug / pk), soft-deleted too.'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only report what would be deleted.',
        )
        parser.add_argument(
            '--noinput',
            '--no-input',
            action='store_false',
            dest='interactive',
            help='Do not ask for confirmation.',
        )
        parser.add_argument(
            '--keep-files',
            action='store_true',
            help='Delete the database rows but leave the media folder on disk.',
        )

    def handle(
        self,
        *args,
        studio,
        dry_run=False,
        interactive=True,
        keep_files=False,
        **options,
    ):
        found = find_studio(studio.strip())
        if found is None:
            raise CommandError(f'No studio {studio!r}.')
        if found.deleted_at is None and found.is_active:
            raise CommandError(
                f'Studio {found.slug!r} is active. Deactivate it first so '
                'listeners, the encoder and radio-studio let go of it.'
            )

        folder = studio_dir(found)
        counts = cascade_counts(found)
        self.stdout.write(f'Studio {found.slug!r} ({found.display_name}):')
        for label, n in counts.items():
            self.stdout.write(f'  {label}: {n}')
        if keep_files:
            self.stdout.write(f'  media folder kept: {folder}')
        elif folder.exists():
            self.stdout.write(f'  media folder: {folder}')
        else:
            self.stdout.write(f'  media folder: {folder} (missing)')

        if dry_run:
            self.stdout.write('Dry run: nothing deleted.')
            return

        if interactive:
            answer = input(
                f'This permanently deletes everything above. '
                f'Type the studio slug ({found.slug}) to confirm: '
            )
            if answer.strip() != found.slug:
                raise CommandError('Confirmation did not match. Nothing deleted.')

        # radio-studio already dropped the studio when it was deactivated, so
        # no sync request is needed.
        with transaction.atomic():
            found.hard_delete()
            # Files go only once the rows are committed, so a rollback never
            # leaves rows pointing at missing files.
            if not keep_files:
                transaction.on_commit(lambda: self._remove_folder(folder))

        self.stdout.write(
            self.style.SUCCESS(f'Deleted studio {found.slug!r} and its content.')
        )

    def _remove_folder(self, folder: Path) -> None:
        if not folder.exists():
            return
        try:
            shutil.rmtree(folder)
        except OSError as e:
            # The rows are already gone; report the leftover instead of failing.
            logger.warning('Could not delete %s: %s', folder, e)
            self.stderr.write(f'Could not delete {folder}: {e}')
