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
from apps.medias.services.duplicates import find_metadata_duplicate
from apps.medias.services.upload import (
    expire_stale_uploads,
    init_upload,
    sweep_orphan_part_files,
)
from apps.studio.models.base import Studio

REQUEST_UPLOAD = """
mutation RequestUpload($studioSlug: String!, $checksum: String) {
  requestUpload(
    studioSlug: $studioSlug
    fileName: "song.mp3"
    sizeBytes: 10
    mimeType: "audio/mpeg"
    checksumSha256: $checksum
  ) {
    uploadId
    duplicateOf { id title }
  }
}
"""

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


class ExactDuplicateTests(UploadCleanupTestBase):
    HASH = "a" * 64

    def setUp(self):
        super().setUp()
        self.client.authenticate(self.user)

    def request(self):
        res = self.client.execute(
            REQUEST_UPLOAD, {"studioSlug": self.studio.slug, "checksum": self.HASH}
        )
        self.assertIsNone(res.errors)
        return res.data["requestUpload"]

    def make_track(self, state, **extra):
        return Track.objects.create(
            studio=self.studio,
            title="Amazing Grace",
            state=state,
            content_hash=self.HASH,
            **extra,
        )

    def test_rejects_file_already_in_library(self):
        existing = self.make_track(Track.State.READY)

        data = self.request()

        self.assertIsNone(data["uploadId"])
        self.assertEqual(data["duplicateOf"]["id"], str(existing.id))
        self.assertFalse(UploadSession.objects.exists())

    def test_replaces_failed_attempt(self):
        failed = self.make_track(Track.State.FAILED)

        data = self.request()

        self.assertIsNotNone(data["uploadId"])
        self.assertIsNone(data["duplicateOf"])
        self.assertFalse(Track.objects.filter(id=failed.id).exists())

    def test_replaces_abandoned_upload(self):
        upload, track, part = self.make_upload()
        Track.objects.filter(id=track.id).update(content_hash=self.HASH)

        data = self.request()

        self.assertIsNotNone(data["uploadId"])
        self.assertFalse(part.exists())
        self.assertFalse(UploadSession.objects.filter(id=upload.id).exists())

    def test_deleted_track_does_not_block_reupload(self):
        self.make_track(Track.State.READY).delete()

        data = self.request()

        self.assertIsNotNone(data["uploadId"])


class MetadataDuplicateTests(UploadCleanupTestBase):
    def make_track(self, title, artist, duration, state=Track.State.READY):
        return Track.objects.create(
            studio=self.studio,
            title=title,
            artist=artist,
            duration_seconds=duration,
            state=state,
            content_hash=f"{title}{artist}{duration}{state}",
        )

    def test_matches_same_title_artist_and_close_length(self):
        original = self.make_track("Amazing Grace", "Choir", 241.0)
        new = self.make_track("amazing grace", "CHOIR", None, Track.State.PENDING)

        self.assertEqual(find_metadata_duplicate(new, 242.5), original)

    def test_ignores_different_length_failed_tracks_and_missing_tags(self):
        self.make_track("Amazing Grace", "Choir", 300.0)
        self.make_track("Amazing Grace", "Choir", 241.0, Track.State.FAILED)
        new = self.make_track("Amazing Grace", "Choir", None, Track.State.PENDING)
        untagged = self.make_track("Amazing Grace", "", None, Track.State.PENDING)

        self.assertIsNone(find_metadata_duplicate(new, 241.0))
        self.assertIsNone(find_metadata_duplicate(untagged, 300.0))


class LoudnessFilterTests(UploadCleanupTestBase):
    def test_uses_studio_target_or_skips_when_disabled(self):
        from apps.medias.tasks import loudness_filter_args

        self.studio.loudness_target_lufs = -16
        self.assertEqual(
            loudness_filter_args(self.studio),
            ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"],
        )
        self.studio.auto_normalize = False
        self.assertEqual(loudness_filter_args(self.studio), [])
