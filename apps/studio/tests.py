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
