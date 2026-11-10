"""Every staff GraphQL field and the chat socket enforce studio permissions."""

import tempfile
from types import SimpleNamespace

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, TransactionTestCase, override_settings

from apps.chat.consumers import ChatConsumer
from apps.common.translations import translate
from apps.medias.models import Track, UploadSession
from apps.studio.models import Studio, StudioMembership
from apps.studio.tests.test_permissions import make_user
from config.schema import schema

Role = StudioMembership.Role
NOT_FOUND = 'studio.studio_not_found'
FORBIDDEN = 'common.forbidden'

# (operation, role that is allowed, role in the same studio that is not)
STUDIO_FIELDS = [
    ('{ listeningTrend(studioId: "zz") { points { active } } }', Role.ANALYST, None),
    ('{ listeningSummaryCount(studioId: "zz") { today } }', Role.ANALYST, None),
    ('{ studioCapacity(studioId: "zz") { diskUsedGb } }', Role.ANALYST, None),
    ('{ currentQueue(studioId: "zz") { items { id } } }', Role.ANALYST, None),
    ('{ listenerOverview(studioId: "zz") { activeNow } }', Role.ANALYST, None),
    (
        '{ tracks(studioSlug: "zz") { edges { node { id } } } }',
        Role.VIEWER,
        Role.ANALYST,
    ),
    ('{ chatMutes(studioSlug: "zz") { id } }', Role.DJ, Role.EDITOR),
    ('{ studioSettings(studioId: "zz") { canEdit } }', Role.VIEWER, None),
    ('{ streamingConfig(studioId: "zz") { username } }', Role.DJ, Role.EDITOR),
    (
        'mutation { regenerateStreamingCredential(studioId: "zz") '
        '{ streamingConfig { username } } }',
        Role.ADMIN,
        Role.DJ,
    ),
    (
        'mutation { updateStudioSettings(studioId: "zz", displayName: "New", '
        'description: "", autoNormalize: true, loudnessTargetLufs: -14) '
        '{ studioSettings { displayName } } }',
        Role.ADMIN,
        Role.EDITOR,
    ),
    ('mutation { skipTrack(studioId: "zz") { ok } }', None, Role.EDITOR),
    (
        'mutation { requestUpload(studioSlug: "zz", fileName: "a.mp3", '
        'sizeBytes: 10, mimeType: "audio/mpeg") { uploadId } }',
        None,  # success path touches the filesystem; covered below
        Role.DJ,
    ),
]


def run(query, user):
    return schema.execute(query, context_value=SimpleNamespace(user=user))


class EndpointPermissionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.studio = Studio.objects.create(slug='zz', display_name='ZZ')
        cls.other = Studio.objects.create(slug='yy', display_name='YY')

    def member(self, role, studio=None):
        user = make_user()
        StudioMembership.objects.create(
            studio=studio or self.studio, user=user, role=role
        )
        return user

    def assertError(self, result, key):
        self.assertIsNotNone(result.errors, 'expected an error')
        self.assertEqual(result.errors[0].message, translate(key))

    def assertOk(self, result):
        self.assertIsNone(result.errors, result.errors)


class StudioFieldPermissionTests(EndpointPermissionBase):
    def test_anonymous_is_rejected(self):
        for query, _, _ in STUDIO_FIELDS:
            with self.subTest(query=query):
                result = run(query, AnonymousUser())
                self.assertIsNotNone(result.errors)
                self.assertNotIn(
                    result.errors[0].message,
                    (translate(NOT_FOUND), translate(FORBIDDEN)),
                )

    def test_member_of_another_studio_sees_not_found(self):
        owner_elsewhere = self.member(Role.OWNER, studio=self.other)
        for query, _, _ in STUDIO_FIELDS:
            with self.subTest(query=query):
                self.assertError(run(query, owner_elsewhere), NOT_FOUND)

    def test_staff_without_membership_sees_not_found(self):
        staff = make_user(is_staff=True)
        for query, _, _ in STUDIO_FIELDS:
            with self.subTest(query=query):
                self.assertError(run(query, staff), NOT_FOUND)

    def test_member_without_perm_is_forbidden(self):
        for query, _, denied in STUDIO_FIELDS:
            if denied is None:
                continue
            with self.subTest(query=query):
                self.assertError(run(query, self.member(denied)), FORBIDDEN)

    def test_member_with_perm_is_allowed(self):
        for query, allowed, _ in STUDIO_FIELDS:
            if allowed is None:
                continue
            with self.subTest(query=query):
                self.assertOk(run(query, self.member(allowed)))

    def test_superuser_is_allowed_without_membership(self):
        admin = make_user(is_superuser=True)
        for query, allowed, _ in STUDIO_FIELDS:
            if allowed is None:
                continue
            with self.subTest(query=query):
                self.assertOk(run(query, admin))

    def test_tracks_are_scoped_to_studio(self):
        Track.objects.create(studio=self.studio, title='mine', content_hash='a' * 64)
        Track.objects.create(studio=self.other, title='theirs', content_hash='b' * 64)
        result = run(
            '{ tracks(studioSlug: "zz") { edges { node { title } } } }',
            self.member(Role.VIEWER),
        )
        self.assertOk(result)
        titles = [e['node']['title'] for e in result.data['tracks']['edges']]
        self.assertEqual(titles, ['mine'])


class ChatHistoryTests(EndpointPermissionBase):
    QUERY = '{ chatMessages(studioSlug: "zz") { body isHidden } }'

    def setUp(self):
        from apps.chat.models import ChatMessage

        ChatMessage.objects.create(
            studio=self.studio, author_type='LISTENER', body='visible'
        )
        ChatMessage.objects.create(
            studio=self.studio, author_type='LISTENER', body='hidden'
        ).delete()

    def bodies(self, user):
        result = run(self.QUERY, user)
        self.assertOk(result)
        return sorted(m['body'] for m in result.data['chatMessages'])

    def test_public_history_hides_hidden_messages(self):
        self.assertEqual(self.bodies(AnonymousUser()), ['visible'])
        self.assertEqual(self.bodies(self.member(Role.EDITOR)), ['visible'])
        self.assertEqual(self.bodies(make_user()), ['visible'])

    def test_moderators_see_hidden_messages(self):
        self.assertEqual(self.bodies(self.member(Role.DJ)), ['hidden', 'visible'])


@override_settings(RADIO_STUDIOS_ROOT=tempfile.mkdtemp())
class MediaMutationPermissionTests(EndpointPermissionBase):
    def make_upload(self, studio=None):
        studio = studio or self.studio
        upload = UploadSession.objects.create(
            studio=studio, original_filename='a.mp3', size_bytes=10
        )
        track = Track.objects.create(
            studio=studio,
            title='a.mp3',
            state=Track.State.UPLOADING,
            content_hash=str(upload.id).replace('-', '') * 2,
            upload_session=upload,
        )
        return upload, track

    def test_request_upload_allowed_for_editor(self):
        result = run(
            'mutation { requestUpload(studioSlug: "zz", fileName: "a.mp3", '
            'sizeBytes: 10, mimeType: "audio/mpeg") { uploadId trackId } }',
            self.member(Role.EDITOR),
        )
        self.assertOk(result)
        self.assertTrue(Track.objects.filter(studio=self.studio).exists())

    def test_request_upload_rejects_inactive_studio(self):
        Studio.objects.filter(pk=self.studio.pk).update(is_active=False)
        result = run(
            'mutation { requestUpload(studioSlug: "zz", fileName: "a.mp3", '
            'sizeBytes: 10, mimeType: "audio/mpeg") { uploadId } }',
            make_user(is_superuser=True),
        )
        self.assertError(result, NOT_FOUND)

    def test_finalize_upload(self):
        upload, _ = self.make_upload()
        query = 'mutation { finalizeUpload(uploadId: "%s") { ok } }' % upload.id
        self.assertError(run(query, self.member(Role.DJ)), FORBIDDEN)
        self.assertError(
            run(query, self.member(Role.OWNER, studio=self.other)), NOT_FOUND
        )
        missing = 'mutation { finalizeUpload(uploadId: "%s") { ok } }' % (
            '00000000-0000-0000-0000-000000000000'
        )
        self.assertError(run(missing, self.member(Role.EDITOR)), NOT_FOUND)

    def test_cancel_upload(self):
        upload, track = self.make_upload()
        query = 'mutation { cancelUpload(uploadId: "%s") { ok } }' % upload.id
        self.assertError(run(query, self.member(Role.VIEWER)), FORBIDDEN)
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

        self.assertOk(run(query, self.member(Role.EDITOR)))
        self.assertFalse(Track.all_objects.filter(pk=track.pk).exists())

    def test_delete_track(self):
        _, track = self.make_upload()
        query = 'mutation { deleteTrack(trackId: "%s") { ok } }' % track.id
        self.assertError(run(query, self.member(Role.DJ)), FORBIDDEN)
        self.assertError(
            run(query, self.member(Role.EDITOR, studio=self.other)), NOT_FOUND
        )
        self.assertTrue(Track.objects.filter(pk=track.pk).exists())

        self.assertOk(run(query, self.member(Role.EDITOR)))
        self.assertFalse(Track.all_objects.filter(pk=track.pk).exists())


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
)
class ChatConsumerPermissionTests(TransactionTestCase):
    def setUp(self):
        self.studio = Studio.objects.create(slug='zz', display_name='ZZ')

    def member(self, role):
        user = make_user()
        StudioMembership.objects.create(studio=self.studio, user=user, role=role)
        return user

    def open(self, user, query=''):
        async def go():
            communicator = WebsocketCommunicator(
                ChatConsumer.as_asgi(), f'/ws/studios/zz/chat/?{query}'
            )
            communicator.scope['user'] = user
            communicator.scope['url_route'] = {'kwargs': {'studio_slug': 'zz'}}
            connected, code = await communicator.connect()
            reply = None
            if connected:
                await communicator.send_json_to(
                    {'type': 'mute_listener', 'listenerClientId': 'abc'}
                )
                reply = await communicator.receive_json_from()
            await communicator.disconnect()
            return connected, code, reply

        return async_to_sync(go)()

    def test_moderator_can_moderate(self):
        connected, _, reply = self.open(self.member(Role.DJ))
        self.assertTrue(connected)
        self.assertEqual(reply['type'], 'listener_muted')

    def test_signed_in_non_moderator_without_listener_id_is_rejected(self):
        connected, code, _ = self.open(self.member(Role.EDITOR))
        self.assertFalse(connected)
        self.assertEqual(code, 4003)

    def test_anonymous_without_listener_id_is_rejected(self):
        connected, code, _ = self.open(AnonymousUser())
        self.assertFalse(connected)
        self.assertEqual(code, 4001)

    def test_signed_in_non_moderator_joins_as_listener(self):
        connected, _, reply = self.open(
            self.member(Role.EDITOR), 'listener_client_id=c1&display_name=Ed'
        )
        self.assertTrue(connected)
        self.assertEqual(reply['type'], 'connected')
        self.assertFalse(reply['isAdmin'])
