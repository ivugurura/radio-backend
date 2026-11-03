import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from graphql_jwt.testcases import JSONWebTokenTestCase

from apps.medias.models import Track, UploadSession
from apps.medias.services.upload import (
    expire_stale_uploads,
    init_upload,
    sweep_orphan_part_files,
)
from apps.studio.models.base import Studio

CANCEL_UPLOAD = """
mutation CancelUpload($uploadId: UUID!) {
  cancelUpload(uploadId: $uploadId) { ok }
}
"""


class UploadCleanupTestBase(JSONWebTokenTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        settings_override = override_settings(RADIO_STUDIOS_ROOT=self._tmp.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.studio = Studio.objects.create(slug="reformation-rw", display_name="RW")
        self.user = get_user_model().objects.create_user(
            email="staff@example.com", password="pw"
        )

    def make_upload(self, finalized=False):
        upload = UploadSession.objects.create(
            studio=self.studio, original_filename="song.mp3", size_bytes=10
        )
        track = Track.objects.create(
            studio=self.studio,
            title="song.mp3",
            state=Track.State.UPLOADING,
            content_hash=str(upload.id),
            upload_session=upload,
        )
        part = init_upload(self.studio, upload)
        part.write_bytes(b"12345")
        if finalized:
            upload.finalized = True
            upload.save(update_fields=["finalized"])
        return upload, track, part

    def age(self, upload, hours):
        UploadSession.objects.filter(id=upload.id).update(
            updated_at=timezone.now() - timedelta(hours=hours)
        )


class CancelUploadMutationTests(UploadCleanupTestBase):
    def test_cancel_removes_part_file_track_and_session(self):
        self.client.authenticate(self.user)
        upload, track, part = self.make_upload()

        res = self.client.execute(CANCEL_UPLOAD, {"uploadId": str(upload.id)})

        self.assertIsNone(res.errors)
        self.assertTrue(res.data["cancelUpload"]["ok"])
        self.assertFalse(part.exists())
        self.assertFalse(Track.objects.filter(id=track.id).exists())
        self.assertFalse(UploadSession.objects.filter(id=upload.id).exists())

    def test_cancel_is_idempotent_and_ignores_finalized_uploads(self):
        self.client.authenticate(self.user)
        upload, track, part = self.make_upload(finalized=True)

        res = self.client.execute(CANCEL_UPLOAD, {"uploadId": str(upload.id)})

        self.assertIsNone(res.errors)
        self.assertTrue(part.exists())
        self.assertTrue(Track.objects.filter(id=track.id).exists())

    def test_cancel_requires_login(self):
        upload, _, _ = self.make_upload()
        res = self.client.execute(CANCEL_UPLOAD, {"uploadId": str(upload.id)})
        self.assertIsNotNone(res.errors)


class ExpireStaleUploadsTests(UploadCleanupTestBase):
    def test_stale_upload_is_failed_and_cleaned(self):
        upload, track, part = self.make_upload()
        self.age(upload, hours=7)

        self.assertEqual(expire_stale_uploads(timedelta(hours=6)), 1)

        track.refresh_from_db()
        self.assertEqual(track.state, Track.State.FAILED)
        self.assertFalse(part.exists())
        self.assertFalse(UploadSession.objects.filter(id=upload.id).exists())

    def test_recent_and_finalized_uploads_are_kept(self):
        recent, recent_track, _ = self.make_upload()
        finalized, _, finalized_part = self.make_upload(finalized=True)
        self.age(finalized, hours=7)

        self.assertEqual(expire_stale_uploads(timedelta(hours=6)), 0)

        recent_track.refresh_from_db()
        self.assertEqual(recent_track.state, Track.State.UPLOADING)
        self.assertTrue(finalized_part.exists())


class SweepOrphanPartFilesTests(UploadCleanupTestBase):
    def test_removes_only_old_unowned_part_files(self):
        _, _, owned_part = self.make_upload()
        incoming = owned_part.parent
        old_orphan = incoming / "orphan-old.part"
        new_orphan = incoming / "orphan-new.part"
        old_orphan.write_bytes(b"x")
        new_orphan.write_bytes(b"x")
        old = time.time() - 7 * 3600
        os.utime(old_orphan, (old, old))
        os.utime(owned_part, (old, old))

        self.assertEqual(sweep_orphan_part_files(timedelta(hours=6)), 1)

        self.assertFalse(old_orphan.exists())
        self.assertTrue(new_orphan.exists())
        self.assertTrue(owned_part.exists())
