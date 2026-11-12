import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.medias.models import Track
from apps.studio.models import StreamingCredential, Studio, StudioMembership
from apps.studio.services.helpers import get_or_create_streaming_credential
from apps.studio.tests.test_permissions import make_user


class DeleteStudioCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        override = override_settings(RADIO_STUDIOS_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)

        self.keep = Studio.objects.create(slug='rw', display_name='RW')
        self.studio = Studio.objects.create(
            slug='en', display_name='EN', is_active=False
        )
        get_or_create_streaming_credential(self.studio)
        user = make_user()
        StudioMembership.objects.create(studio=self.studio, user=user)
        StudioMembership.objects.create(studio=self.keep, user=user)
        Track.objects.create(studio=self.studio, content_hash='a' * 64)
        Track.objects.create(studio=self.studio, content_hash='b' * 64).delete()
        Track.objects.create(studio=self.keep, content_hash='c' * 64)

        self.folder = self.root / 'en' / 'library'
        self.folder.mkdir(parents=True)
        (self.folder / 'x.mp3').write_bytes(b'mp3')
        (self.root / 'rw').mkdir()

    def run_command(self, *args):
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('delete_studio', *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_deletes_rows_soft_deleted_too_and_folder(self):
        self.run_command('en', '--noinput')

        self.assertFalse(Studio.all_objects.filter(slug='en').exists())
        self.assertFalse(Track.all_objects.filter(studio_id=self.studio.pk).exists())
        self.assertFalse(
            StudioMembership.all_objects.filter(studio_id=self.studio.pk).exists()
        )
        self.assertFalse(
            StreamingCredential.objects.filter(studio_id=self.studio.pk).exists()
        )
        self.assertFalse((self.root / 'en').exists())
        # Other studios are untouched.
        self.assertEqual(Track.objects.filter(studio=self.keep).count(), 1)
        self.assertTrue((self.root / 'rw').exists())

    def test_refuses_active_studio(self):
        with self.assertRaises(CommandError):
            self.run_command('rw', '--noinput')
        self.assertTrue(Studio.objects.filter(slug='rw').exists())

    def test_finds_soft_deleted_studio(self):
        self.studio.delete()
        self.run_command('en', '--noinput')
        self.assertFalse(Studio.all_objects.filter(slug='en').exists())

    def test_dry_run_deletes_nothing(self):
        out = self.run_command('en', '--dry-run')
        self.assertIn('medias.Track: 2', out)
        self.assertTrue(Studio.objects.filter(slug='en').exists())
        self.assertTrue(self.folder.exists())

    def test_keep_files(self):
        self.run_command('en', '--noinput', '--keep-files')
        self.assertFalse(Studio.all_objects.filter(slug='en').exists())
        self.assertTrue(self.folder.exists())

    def test_wrong_confirmation_aborts(self):
        with mock.patch('builtins.input', return_value='rw'):
            with self.assertRaises(CommandError):
                self.run_command('en')
        self.assertTrue(Studio.objects.filter(slug='en').exists())

    def test_unknown_studio(self):
        with self.assertRaises(CommandError):
            self.run_command('fr', '--noinput')
