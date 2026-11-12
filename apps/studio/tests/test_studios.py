from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase, override_settings

from apps.common.translations import translate
from apps.studio.models import StreamingCredential, Studio, StudioMembership
from apps.studio.services.permissions import accessible_studios
from apps.studio.tests.test_members import run
from apps.studio.tests.test_permissions import make_user

Role = StudioMembership.Role

STUDIOS = (
    'query($all: Boolean) { studios(includeInactive: $all) { studioId isActive '
    'memberCount trackCount hasStreamingCredential bitrateKbps sampleRateHz } }'
)
AVAILABLE = '{ availableStudioSlugs }'
PUBLIC = '{ publicStudios { studioId displayName } }'
CREATE = (
    'mutation($id: String!, $name: String!, $owner: UUID) { createStudio('
    'studioId: $id, displayName: $name, description: " About ", '
    'ownerUserId: $owner) { studio { studioId displayName description isActive '
    'memberCount hasStreamingCredential bitrateKbps sampleRateHz channels } } }'
)
SET_ACTIVE = (
    'mutation($id: String!, $active: Boolean!) { setStudioActive('
    'studioId: $id, active: $active) { studio { studioId isActive } } }'
)

# Media folders are created on commit; keep tests off the real RADIO_ROOT.
FOLDERS = 'apps.studio.services.studios._create_media_folders'


class StudioAdminTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rw = Studio.objects.create(slug='rw', display_name='RW')
        cls.superuser = make_user(is_superuser=True)

    def assertError(self, result, key, **kwargs):
        self.assertIsNotNone(result.errors, 'expected an error')
        self.assertEqual(result.errors[0].message, translate(key, **kwargs))

    def assertOk(self, result):
        self.assertIsNone(result.errors, result.errors)
        return result.data


class StudioQueryTests(StudioAdminTestBase):
    def test_superuser_lists_all_studios_with_counts(self):
        Studio.objects.create(slug='en', display_name='EN', is_active=False)
        StudioMembership.objects.create(studio=self.rw, user=make_user())
        removed = StudioMembership.objects.create(studio=self.rw, user=make_user())
        removed.delete()  # soft-deleted members aren't counted

        data = self.assertOk(run(STUDIOS, self.superuser))['studios']
        self.assertEqual(
            [(s['studioId'], s['isActive'], s['memberCount']) for s in data],
            [('en', False, 0), ('rw', True, 1)],
        )
        active = self.assertOk(run(STUDIOS, self.superuser, all=False))['studios']
        self.assertEqual([s['studioId'] for s in active], ['rw'])

    def test_non_superusers_are_refused(self):
        owner = make_user()
        StudioMembership.objects.create(studio=self.rw, user=owner, role=Role.OWNER)
        self.assertError(run(STUDIOS, owner), 'common.forbidden')
        self.assertError(run(AVAILABLE, owner), 'common.forbidden')
        self.assertIsNotNone(run(STUDIOS, AnonymousUser()).errors)

    def test_available_slugs_skip_taken_and_soft_deleted(self):
        self.assertEqual(
            self.assertOk(run(AVAILABLE, self.superuser))['availableStudioSlugs'],
            ['en', 'fr', 'sw'],
        )
        Studio.objects.create(slug='en', display_name='EN').delete()
        self.assertEqual(
            self.assertOk(run(AVAILABLE, self.superuser))['availableStudioSlugs'],
            ['fr', 'sw'],
        )

    def test_public_studios_lists_active_only_for_anyone(self):
        Studio.objects.create(slug='en', display_name='EN', is_active=False)
        data = self.assertOk(run(PUBLIC, AnonymousUser()))['publicStudios']
        self.assertEqual(data, [{'studioId': 'rw', 'displayName': 'RW'}])


@override_settings(DEFAULT_TARGET_BR_KBPS=128, DEFAULT_TARGET_SR_HZ=48000)
class CreateStudioTests(StudioAdminTestBase):
    def test_creates_studio_with_owner_credentials_and_folders(self):
        owner = make_user()
        with mock.patch(FOLDERS) as folders:
            with self.captureOnCommitCallbacks(execute=True):
                result = run(
                    CREATE,
                    self.superuser,
                    id=' EN ',
                    name=' English ',
                    owner=str(owner.pk),
                )
        studio = self.assertOk(result)['createStudio']['studio']
        self.assertEqual(
            studio,
            {
                'studioId': 'en',
                'displayName': 'English',
                'description': 'About',
                'isActive': True,
                'memberCount': 1,
                'hasStreamingCredential': True,
                'bitrateKbps': 128,
                'sampleRateHz': 48000,
                'channels': 2,
            },
        )
        created = Studio.objects.get(slug='en')
        self.assertEqual(
            StudioMembership.objects.get(studio=created, user=owner).role, Role.OWNER
        )
        self.assertTrue(StreamingCredential.objects.filter(studio=created).exists())
        folders.assert_called_once_with(created)
        self.assertIn(created, [s for s, _ in accessible_studios(owner)])

    def test_owner_is_optional(self):
        with mock.patch(FOLDERS):
            result = run(CREATE, self.superuser, id='en', name='English')
        self.assertEqual(
            self.assertOk(result)['createStudio']['studio']['memberCount'], 0
        )

    def test_rejects_bad_taken_and_legacy_slugs(self):
        choices = 'en, rw, fr, sw'
        for slug in ('de', 'reformation-rw', ''):
            self.assertError(
                run(CREATE, self.superuser, id=slug, name='X'),
                'studio.invalid_slug',
                choices=choices,
            )
        self.assertError(
            run(CREATE, self.superuser, id='rw', name='X'),
            'studio.slug_taken',
            slug='rw',
        )
        Studio.objects.create(slug='en', display_name='EN').delete()
        self.assertError(
            run(CREATE, self.superuser, id='en', name='X'),
            'studio.slug_taken',
            slug='en',
        )

    def test_rejects_bad_name_and_owner(self):
        self.assertError(
            run(CREATE, self.superuser, id='en', name='  '),
            'studio.invalid_display_name',
            max=120,
        )
        disabled = make_user(is_active=False)
        self.assertError(
            run(CREATE, self.superuser, id='en', name='EN', owner=str(disabled.pk)),
            'auth.user_disabled',
        )
        self.assertError(
            run(
                CREATE,
                self.superuser,
                id='en',
                name='EN',
                owner='00000000-0000-0000-0000-000000000000',
            ),
            'auth.user_not_found',
        )
        self.assertFalse(Studio.all_objects.filter(slug='en').exists())

    def test_non_superusers_are_refused(self):
        owner = make_user()
        StudioMembership.objects.create(studio=self.rw, user=owner, role=Role.OWNER)
        self.assertError(run(CREATE, owner, id='en', name='EN'), 'common.forbidden')
        self.assertFalse(Studio.all_objects.filter(slug='en').exists())


@override_settings(STUDIO_TOKEN='secret')
class SetStudioActiveTests(StudioAdminTestBase):
    def setUp(self):
        self.en = Studio.objects.create(slug='en', display_name='EN')

    def test_deactivate_hides_studio_and_reactivate_restores_it(self):
        member = make_user()
        StudioMembership.objects.create(studio=self.en, user=member)

        data = self.assertOk(run(SET_ACTIVE, self.superuser, id='en', active=False))
        self.assertEqual(
            data['setStudioActive']['studio'], {'studioId': 'en', 'isActive': False}
        )
        self.assertEqual(accessible_studios(member), [])
        response = Client().get('/api/studios', HTTP_AUTHORIZATION='Bearer secret')
        self.assertEqual([s['slug'] for s in response.json()], ['rw'])

        self.assertOk(run(SET_ACTIVE, self.superuser, id='en', active=True))
        self.en.refresh_from_db()
        self.assertTrue(self.en.is_active)

    def test_last_active_studio_stays_active(self):
        self.assertOk(run(SET_ACTIVE, self.superuser, id='en', active=False))
        self.assertError(
            run(SET_ACTIVE, self.superuser, id='rw', active=False),
            'studio.last_active_studio',
        )
        self.rw.refresh_from_db()
        self.assertTrue(self.rw.is_active)

    def test_unknown_studio_and_non_superusers(self):
        self.assertError(
            run(SET_ACTIVE, self.superuser, id='zz', active=False),
            'studio.studio_not_found',
        )
        owner = make_user()
        StudioMembership.objects.create(studio=self.en, user=owner, role=Role.OWNER)
        self.assertError(
            run(SET_ACTIVE, owner, id='en', active=False), 'common.forbidden'
        )
