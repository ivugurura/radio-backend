from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.common.translations import translate
from apps.studio.models import Studio, StudioMembership
from apps.studio.services.permissions import Perm
from apps.studio.tests.test_permissions import make_user
from config.schema import schema

Role = StudioMembership.Role

MEMBERS = '{ studioMembers(studioId: "zz") { user { email } role canManage } }'
# Adding a member goes through inviteUser: existing accounts are added at once.
ADD = (
    'mutation($email: String!, $role: StudioRole!) { inviteUser('
    'studioId: "zz", email: $email, role: $role) '
    '{ created inviteLink user { email } } }'
)
UPDATE = (
    'mutation($userId: UUID!, $role: StudioRole!) { updateStudioMemberRole('
    'studioId: "zz", userId: $userId, role: $role) { member { role } } }'
)
REMOVE = (
    'mutation($userId: UUID!) { removeStudioMember(studioId: "zz", userId: $userId) '
    '{ ok } }'
)
ME = (
    '{ me { isSuperuser studioAccess { studioId displayName role permissions '
    'assignableRoles } } }'
)


def run(query, user, **variables):
    return schema.execute(
        query, variable_values=variables, context_value=SimpleNamespace(user=user)
    )


class MemberTestBase(TestCase):
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

    def role_of(self, user):
        return (
            StudioMembership.objects.filter(studio=self.studio, user=user)
            .values_list('role', flat=True)
            .first()
        )

    def assertError(self, result, key):
        self.assertIsNotNone(result.errors, 'expected an error')
        self.assertEqual(result.errors[0].message, translate(key))

    def assertOk(self, result):
        self.assertIsNone(result.errors, result.errors)
        return result.data


class StudioMembersQueryTests(MemberTestBase):
    def test_lists_members_ordered_by_role_with_can_manage(self):
        admin = self.member(Role.ADMIN)
        owner = self.member(Role.OWNER)
        dj = self.member(Role.DJ)
        self.member(Role.OWNER, studio=self.other)  # not listed

        data = self.assertOk(run(MEMBERS, admin))['studioMembers']
        self.assertEqual(
            [(m['user']['email'], m['role'], m['canManage']) for m in data],
            [
                (owner.email, 'OWNER', False),
                (admin.email, 'ADMIN', False),  # self
                (dj.email, 'DJ', True),
            ],
        )

    def test_requires_manage_members(self):
        self.assertError(run(MEMBERS, self.member(Role.DJ)), 'common.forbidden')
        self.assertError(
            run(MEMBERS, self.member(Role.OWNER, studio=self.other)),
            'studio.studio_not_found',
        )
        self.assertIsNotNone(run(MEMBERS, AnonymousUser()).errors)

    def test_superuser_without_membership(self):
        self.member(Role.OWNER)
        data = self.assertOk(run(MEMBERS, make_user(is_superuser=True)))
        self.assertEqual(data['studioMembers'][0]['canManage'], True)


class AddStudioMemberTests(MemberTestBase):
    def test_admin_adds_existing_account_with_lower_role(self):
        admin = self.member(Role.ADMIN)
        target = make_user()
        data = self.assertOk(run(ADD, admin, email=target.email.upper(), role='DJ'))
        self.assertFalse(data['inviteUser']['created'])
        self.assertIsNone(data['inviteUser']['inviteLink'])  # has a password
        self.assertEqual(self.role_of(target), Role.DJ)

    def test_admin_cannot_add_admin_or_owner(self):
        admin = self.member(Role.ADMIN)
        for role in ('ADMIN', 'OWNER'):
            with self.subTest(role=role):
                result = run(ADD, admin, email=make_user().email, role=role)
                self.assertError(result, 'studio.role_not_allowed')

    def test_owner_adds_owner(self):
        owner = self.member(Role.OWNER)
        target = make_user()
        self.assertOk(run(ADD, owner, email=target.email, role='OWNER'))
        self.assertEqual(self.role_of(target), Role.OWNER)

    def test_new_email_needs_names_and_disabled_account_is_refused(self):
        owner = self.member(Role.OWNER)
        result = run(ADD, owner, email='nobody@example.com', role='DJ')
        self.assertError(result, 'auth.name_required')
        inactive = make_user(is_active=False)
        result = run(ADD, owner, email=inactive.email, role='DJ')
        self.assertError(result, 'auth.user_disabled')

    def test_existing_member(self):
        owner = self.member(Role.OWNER)
        dj = self.member(Role.DJ)
        result = run(ADD, owner, email=dj.email, role='VIEWER')
        self.assertError(result, 'studio.member_exists')

    def test_removed_member_can_be_added_again(self):
        owner = self.member(Role.OWNER)
        dj = self.member(Role.DJ)
        self.assertOk(run(REMOVE, owner, userId=str(dj.pk)))
        self.assertOk(run(ADD, owner, email=dj.email, role='EDITOR'))
        self.assertEqual(self.role_of(dj), Role.EDITOR)

    def test_requires_manage_members(self):
        result = run(
            ADD, self.member(Role.EDITOR), email=make_user().email, role='VIEWER'
        )
        self.assertError(result, 'common.forbidden')
        result = run(
            ADD,
            self.member(Role.OWNER, studio=self.other),
            email=make_user().email,
            role='VIEWER',
        )
        self.assertError(result, 'studio.studio_not_found')


class UpdateStudioMemberRoleTests(MemberTestBase):
    def test_admin_changes_lower_roles(self):
        admin = self.member(Role.ADMIN)
        dj = self.member(Role.DJ)
        data = self.assertOk(run(UPDATE, admin, userId=str(dj.pk), role='EDITOR'))
        self.assertEqual(data['updateStudioMemberRole']['member']['role'], 'EDITOR')
        self.assertEqual(self.role_of(dj), Role.EDITOR)

    def test_admin_cannot_promote_to_admin(self):
        admin = self.member(Role.ADMIN)
        dj = self.member(Role.DJ)
        result = run(UPDATE, admin, userId=str(dj.pk), role='ADMIN')
        self.assertError(result, 'studio.role_not_allowed')
        self.assertEqual(self.role_of(dj), Role.DJ)

    def test_admin_cannot_touch_peer_or_owner(self):
        admin = self.member(Role.ADMIN)
        for role in (Role.ADMIN, Role.OWNER):
            with self.subTest(role=role):
                peer = self.member(role)
                result = run(UPDATE, admin, userId=str(peer.pk), role='VIEWER')
                self.assertError(result, 'studio.role_not_allowed')
                self.assertEqual(self.role_of(peer), role)

    def test_cannot_change_own_role(self):
        owner = self.member(Role.OWNER)
        self.member(Role.OWNER)
        result = run(UPDATE, owner, userId=str(owner.pk), role='VIEWER')
        self.assertError(result, 'studio.cannot_change_own_membership')

    def test_last_owner_cannot_be_demoted(self):
        owner = self.member(Role.OWNER)
        superuser = make_user(is_superuser=True)
        result = run(UPDATE, superuser, userId=str(owner.pk), role='ADMIN')
        self.assertError(result, 'studio.last_owner')
        self.assertEqual(self.role_of(owner), Role.OWNER)

    def test_owner_demotes_another_owner(self):
        owner = self.member(Role.OWNER)
        other_owner = self.member(Role.OWNER)
        self.assertOk(run(UPDATE, owner, userId=str(other_owner.pk), role='ADMIN'))
        self.assertEqual(self.role_of(other_owner), Role.ADMIN)

    def test_unknown_member(self):
        owner = self.member(Role.OWNER)
        outsider = self.member(Role.DJ, studio=self.other)
        result = run(UPDATE, owner, userId=str(outsider.pk), role='VIEWER')
        self.assertError(result, 'studio.member_not_found')


class RemoveStudioMemberTests(MemberTestBase):
    def test_admin_removes_lower_role(self):
        admin = self.member(Role.ADMIN)
        dj = self.member(Role.DJ)
        self.assertOk(run(REMOVE, admin, userId=str(dj.pk)))
        self.assertIsNone(self.role_of(dj))
        # soft delete: the row is kept
        self.assertTrue(
            StudioMembership.all_objects.filter(studio=self.studio, user=dj).exists()
        )

    def test_admin_cannot_remove_admin(self):
        admin = self.member(Role.ADMIN)
        peer = self.member(Role.ADMIN)
        result = run(REMOVE, admin, userId=str(peer.pk))
        self.assertError(result, 'studio.role_not_allowed')

    def test_cannot_remove_self(self):
        admin = self.member(Role.ADMIN)
        result = run(REMOVE, admin, userId=str(admin.pk))
        self.assertError(result, 'studio.cannot_change_own_membership')

    def test_last_owner_cannot_be_removed(self):
        owner = self.member(Role.OWNER)
        result = run(REMOVE, make_user(is_superuser=True), userId=str(owner.pk))
        self.assertError(result, 'studio.last_owner')

    def test_removed_member_loses_access(self):
        owner = self.member(Role.OWNER)
        dj = self.member(Role.DJ)
        self.assertOk(run(REMOVE, owner, userId=str(dj.pk)))
        self.assertError(
            run('{ streamingConfig(studioId: "zz") { username } }', dj),
            'studio.studio_not_found',
        )


class MeStudioAccessTests(MemberTestBase):
    def test_member_sees_own_studios_and_perms(self):
        admin = self.member(Role.ADMIN)
        StudioMembership.objects.create(studio=self.other, user=admin, role=Role.DJ)
        Studio.objects.create(slug='xx', display_name='Off', is_active=False)
        StudioMembership.objects.create(
            studio=Studio.objects.get(slug='xx'), user=admin, role=Role.OWNER
        )

        data = self.assertOk(run(ME, admin))['me']
        self.assertFalse(data['isSuperuser'])
        access = {a['studioId']: a for a in data['studioAccess']}
        self.assertEqual(set(access), {'yy', 'zz'})  # inactive studio hidden
        self.assertEqual(access['zz']['role'], 'ADMIN')
        self.assertEqual(set(access['zz']['permissions']), {p.value for p in Perm})
        self.assertEqual(
            access['zz']['assignableRoles'], ['EDITOR', 'DJ', 'ANALYST', 'VIEWER']
        )
        self.assertEqual(access['yy']['role'], 'DJ')
        self.assertNotIn('MANAGE_MEMBERS', access['yy']['permissions'])
        self.assertEqual(access['yy']['assignableRoles'], [])

    def test_superuser_sees_all_active_studios(self):
        data = self.assertOk(run(ME, make_user(is_superuser=True)))['me']
        self.assertTrue(data['isSuperuser'])
        self.assertEqual([a['studioId'] for a in data['studioAccess']], ['yy', 'zz'])
        self.assertIsNone(data['studioAccess'][0]['role'])
        self.assertEqual(len(data['studioAccess'][0]['assignableRoles']), 6)

    def test_user_without_memberships(self):
        data = self.assertOk(run(ME, make_user()))['me']
        self.assertEqual(data['studioAccess'], [])

    def test_studio_access_not_exposed_for_other_users(self):
        owner = self.member(Role.OWNER)
        self.member(Role.DJ)
        result = run(
            '{ studioMembers(studioId: "zz") { user { studioAccess { studioId } } } }',
            owner,
        )
        data = self.assertOk(result)['studioMembers']
        others = [m['user']['studioAccess'] for m in data[1:]]
        self.assertEqual(others, [[]])

    def test_query_count_is_flat(self):
        user = self.member(Role.ADMIN)
        StudioMembership.objects.create(studio=self.other, user=user, role=Role.DJ)
        with self.assertNumQueries(1):
            self.assertOk(run('{ me { studioAccess { studioId permissions } } }', user))
