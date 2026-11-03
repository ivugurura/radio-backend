from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from graphql_jwt.testcases import JSONWebTokenTestCase

from apps.studio.models.base import Studio, StudioMembership
from apps.studio.services.studio_control import StudioControlError

SKIP_TRACK = """
mutation SkipTrack($studioId: String!) {
  skipTrack(studioId: $studioId) { ok }
}
"""


def _make_user(n: int, **extra):
    return get_user_model().objects.create_user(
        email=f"user{n}@example.com",
        password="pass-1234",
        user_name=f"user{n}",
        phone=f"+2507800000{n}",
        first_name="Test",
        last_name=str(n),
        **extra,
    )


@override_settings(STUDIO_TOKEN="secret", STUDIO_INTERNAL_URL="http://studio")
class SkipTrackMutationTests(JSONWebTokenTestCase):
    def setUp(self):
        self.studio = Studio.objects.create(slug="reformation-rw", display_name="RW")
        self.admin = _make_user(1)
        StudioMembership.objects.create(
            studio=self.studio, user=self.admin, role=StudioMembership.Role.ADMIN
        )
        self.viewer = _make_user(2)
        StudioMembership.objects.create(
            studio=self.studio, user=self.viewer, role=StudioMembership.Role.VIEWER
        )

    def _skip(self):
        return self.client.execute(SKIP_TRACK, {"studioId": self.studio.slug})

    @mock.patch("apps.studio.schema.mutations.playback.skip_track")
    def test_admin_skips_current_track(self, skip):
        self.client.authenticate(self.admin)
        res = self._skip()
        self.assertIsNone(res.errors)
        self.assertTrue(res.data["skipTrack"]["ok"])
        skip.assert_called_once_with("reformation-rw")

    @mock.patch("apps.studio.schema.mutations.playback.skip_track")
    def test_non_admin_member_is_refused(self, skip):
        self.client.authenticate(self.viewer)
        res = self._skip()
        self.assertIsNotNone(res.errors)
        skip.assert_not_called()

    @mock.patch("apps.studio.schema.mutations.playback.skip_track")
    def test_anonymous_is_refused(self, skip):
        res = self._skip()
        self.assertIsNotNone(res.errors)
        skip.assert_not_called()

    @mock.patch(
        "apps.studio.schema.mutations.playback.skip_track",
        side_effect=StudioControlError("Live source is on air"),
    )
    def test_studio_refusal_is_reported(self, _skip):
        self.client.authenticate(self.admin)
        res = self._skip()
        self.assertIn("Live source is on air", res.errors[0].message)


@override_settings(STUDIO_TOKEN="secret", STUDIO_INTERNAL_URL="http://studio/")
class SkipTrackServiceTests(JSONWebTokenTestCase):
    @mock.patch("apps.studio.services.studio_control.urllib.request.urlopen")
    def test_posts_to_studio_with_backend_token(self, urlopen):
        from apps.studio.services.studio_control import skip_track

        skip_track("reformation-rw")

        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "http://studio/studios/reformation-rw/skip")
        self.assertEqual(req.get_header("Authorization"), "Bearer secret")


STUDIO_SETTINGS = """
query StudioSettings($studioId: String!) {
  studioSettings(studioId: $studioId) {
    displayName autoNormalize loudnessTargetLufs sampleRateHz canEdit
  }
}
"""

UPDATE_STUDIO_SETTINGS = """
mutation UpdateStudioSettings(
  $studioId: String!, $displayName: String!, $description: String!,
  $autoNormalize: Boolean!, $loudnessTargetLufs: Float!
) {
  updateStudioSettings(
    studioId: $studioId, displayName: $displayName, description: $description,
    autoNormalize: $autoNormalize, loudnessTargetLufs: $loudnessTargetLufs
  ) { studioSettings { displayName loudnessTargetLufs } }
}
"""


class StudioSettingsTests(JSONWebTokenTestCase):
    def setUp(self):
        self.studio = Studio.objects.create(slug="reformation-rw", display_name="RW")
        self.admin = _make_user(1)
        StudioMembership.objects.create(
            studio=self.studio, user=self.admin, role=StudioMembership.Role.ADMIN
        )
        self.viewer = _make_user(2)
        StudioMembership.objects.create(
            studio=self.studio, user=self.viewer, role=StudioMembership.Role.VIEWER
        )

    def update(self, **overrides):
        variables = {
            "studioId": self.studio.slug,
            "displayName": "Radio RW",
            "description": "Gospel radio",
            "autoNormalize": True,
            "loudnessTargetLufs": -16,
            **overrides,
        }
        return self.client.execute(UPDATE_STUDIO_SETTINGS, variables)

    def test_settings_report_whether_user_can_edit(self):
        for user, can_edit in ((self.admin, True), (self.viewer, False)):
            self.client.authenticate(user)
            res = self.client.execute(STUDIO_SETTINGS, {"studioId": self.studio.slug})
            self.assertIsNone(res.errors)
            settings = res.data["studioSettings"]
            self.assertEqual(settings["canEdit"], can_edit)
            self.assertEqual(settings["sampleRateHz"], 48000)

    def test_admin_updates_settings(self):
        self.client.authenticate(self.admin)

        res = self.update()

        self.assertIsNone(res.errors)
        self.studio.refresh_from_db()
        self.assertEqual(self.studio.display_name, "Radio RW")
        self.assertEqual(float(self.studio.loudness_target_lufs), -16.0)

    def test_viewer_cannot_update(self):
        self.client.authenticate(self.viewer)

        self.assertIsNotNone(self.update().errors)
        self.studio.refresh_from_db()
        self.assertEqual(self.studio.display_name, "RW")

    def test_rejects_blank_name_and_out_of_range_loudness(self):
        self.client.authenticate(self.admin)
        for overrides in (
            {"displayName": "  "},
            {"loudnessTargetLufs": -40},
            {"loudnessTargetLufs": 0},
        ):
            self.assertIsNotNone(self.update(**overrides).errors, overrides)
