from io import StringIO
from types import SimpleNamespace

import graphene
from django.contrib.auth.models import AnonymousUser
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.common.translations import translate
from apps.studio.models import Studio, StudioMembership
from apps.studio.services.permissions import (
    ALL_PERMS,
    ROLE_PERMS,
    Perm,
    can_assign_role,
    clear_role_cache,
    get_permissions,
    get_role,
    has_perm,
    has_studio_access,
    require_perm,
)
from apps.users.models import User

Role = StudioMembership.Role

# The agreed matrix, spelled out so an accidental change to ROLE_PERMS fails.
EXPECTED = {
    Role.OWNER: set(Perm),
    Role.ADMIN: set(Perm),
    Role.EDITOR: {Perm.VIEW_ANALYTICS, Perm.VIEW_MEDIA, Perm.MANAGE_MEDIA},
    Role.DJ: {
        Perm.VIEW_ANALYTICS,
        Perm.VIEW_MEDIA,
        Perm.CONTROL_PLAYBACK,
        Perm.MODERATE_CHAT,
        Perm.VIEW_STREAM_CREDS,
    },
    Role.ANALYST: {Perm.VIEW_ANALYTICS},
    Role.VIEWER: {Perm.VIEW_ANALYTICS, Perm.VIEW_MEDIA},
}

_counter = 0


def make_user(**extra):
    global _counter
    _counter += 1
    return User.objects.create_user(
        email=f'user{_counter}@example.com',
        password='x',
        user_name=f'user{_counter}',
        phone=f'+2507800000{_counter:02d}',
        first_name='Test',
        last_name=f'User{_counter}',
        **extra,
    )


class PermissionTestBase(TestCase):
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


class RolePermissionMatrixTests(PermissionTestBase):
    def test_every_role_is_mapped(self):
        self.assertEqual(set(ROLE_PERMS), set(Role.values))

    def test_matrix(self):
        for role, expected in EXPECTED.items():
            with self.subTest(role=role):
                user = self.member(role)
                self.assertEqual(set(get_permissions(user, self.studio)), expected)
                for perm in Perm:
                    self.assertEqual(
                        has_perm(user, self.studio, perm), perm in expected, perm
                    )

    def test_membership_does_not_leak_to_other_studios(self):
        user = self.member(Role.OWNER)
        self.assertEqual(get_permissions(user, self.other), frozenset())
        self.assertFalse(has_studio_access(user, self.other))
        self.assertTrue(has_studio_access(user, self.studio))

    def test_superuser_has_everything_without_membership(self):
        admin = make_user(is_superuser=True, is_staff=True)
        self.assertEqual(get_permissions(admin, self.studio), ALL_PERMS)
        self.assertTrue(has_studio_access(admin, self.other))

    def test_staff_flag_alone_grants_nothing(self):
        staff = make_user(is_staff=True)
        self.assertEqual(get_permissions(staff, self.studio), frozenset())
        self.assertFalse(has_studio_access(staff, self.studio))

    def test_anonymous_and_non_member(self):
        for user in (AnonymousUser(), None, make_user()):
            with self.subTest(user=user):
                self.assertIsNone(get_role(user, self.studio))
                self.assertEqual(get_permissions(user, self.studio), frozenset())


class MembershipLifecycleTests(PermissionTestBase):
    def test_soft_deleted_membership_gives_no_access(self):
        user = self.member(Role.ADMIN)
        StudioMembership.objects.get(user=user).delete()
        self.assertIsNone(get_role(user, self.studio))

    def test_removed_member_can_be_added_back(self):
        user = self.member(Role.DJ)
        StudioMembership.objects.get(user=user).delete()
        StudioMembership.objects.create(studio=self.studio, user=user, role=Role.EDITOR)
        self.assertEqual(get_role(user, self.studio), Role.EDITOR)

    def test_one_live_membership_per_studio(self):
        user = self.member(Role.DJ)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudioMembership.objects.create(
                studio=self.studio, user=user, role=Role.VIEWER
            )


class RoleCacheTests(PermissionTestBase):
    def test_one_query_per_studio(self):
        user = self.member(Role.EDITOR)
        with self.assertNumQueries(1):
            for perm in Perm:
                has_perm(user, self.studio, perm)
        with self.assertNumQueries(1):
            has_perm(user, self.other, Perm.VIEW_MEDIA)

    def test_clear_role_cache(self):
        user = self.member(Role.VIEWER)
        self.assertFalse(has_perm(user, self.studio, Perm.MANAGE_MEDIA))
        StudioMembership.objects.filter(user=user).update(role=Role.EDITOR)
        self.assertFalse(has_perm(user, self.studio, Perm.MANAGE_MEDIA))
        clear_role_cache(user)
        self.assertTrue(has_perm(user, self.studio, Perm.MANAGE_MEDIA))


class CanAssignRoleTests(PermissionTestBase):
    def test_owner_assigns_any_role(self):
        owner = self.member(Role.OWNER)
        for role in Role.values:
            self.assertTrue(can_assign_role(owner, self.studio, role), role)

    def test_admin_assigns_only_lower_roles(self):
        admin = self.member(Role.ADMIN)
        self.assertFalse(can_assign_role(admin, self.studio, Role.OWNER))
        self.assertFalse(can_assign_role(admin, self.studio, Role.ADMIN))
        for role in (Role.EDITOR, Role.DJ, Role.ANALYST, Role.VIEWER):
            self.assertTrue(can_assign_role(admin, self.studio, role), role)

    def test_roles_without_manage_members_assign_nothing(self):
        for role in (Role.EDITOR, Role.DJ, Role.ANALYST, Role.VIEWER):
            user = self.member(role)
            self.assertFalse(can_assign_role(user, self.studio, Role.VIEWER), role)

    def test_superuser_assigns_any_role_anywhere(self):
        admin = make_user(is_superuser=True)
        self.assertTrue(can_assign_role(admin, self.other, Role.OWNER))

    def test_unknown_role(self):
        owner = self.member(Role.OWNER)
        self.assertFalse(can_assign_role(owner, self.studio, 'GOD'))

    def test_owner_elsewhere_cannot_assign_here(self):
        owner = self.member(Role.OWNER, studio=self.other)
        self.assertFalse(can_assign_role(owner, self.studio, Role.VIEWER))


class _Query(graphene.ObjectType):
    rotate = graphene.String(studio_id=graphene.String(required=True))

    @require_perm(Perm.ROTATE_STREAM_CREDS)
    def resolve_rotate(self, info, studio):
        return studio.slug


_schema = graphene.Schema(query=_Query)


class RequirePermTests(PermissionTestBase):
    def run_query(self, user, studio_id='zz'):
        result = _schema.execute(
            '{ rotate(studioId: "%s") }' % studio_id,
            context_value=SimpleNamespace(user=user),
        )
        return result.data['rotate'] if result.data else None, result.errors

    def test_allowed_member_gets_resolved_studio(self):
        data, errors = self.run_query(self.member(Role.ADMIN))
        self.assertIsNone(errors)
        self.assertEqual(data, 'zz')

    def test_anonymous_is_rejected(self):
        data, errors = self.run_query(AnonymousUser())
        self.assertIsNone(data)
        self.assertIn('permission', errors[0].message.lower())

    def test_member_without_perm_is_forbidden(self):
        data, errors = self.run_query(self.member(Role.DJ))
        self.assertIsNone(data)
        self.assertEqual(errors[0].message, translate('common.forbidden'))

    def test_non_member_sees_not_found(self):
        _, errors = self.run_query(self.member(Role.OWNER, studio=self.other))
        self.assertEqual(errors[0].message, translate('studio.studio_not_found'))

    def test_unknown_studio_sees_not_found(self):
        _, errors = self.run_query(make_user(is_superuser=True), studio_id='nope')
        self.assertEqual(errors[0].message, translate('studio.studio_not_found'))


class GrantStudioRoleCommandTests(PermissionTestBase):
    def call(self, *args):
        call_command('grant_studio_role', *args, stdout=StringIO())

    def test_grant_change_remove(self):
        user = make_user()
        self.call(user.email, 'zz', 'DJ')
        self.assertEqual(get_role(user, self.studio), Role.DJ)

        clear_role_cache(user)
        self.call(user.email.upper(), 'zz', 'ADMIN')
        self.assertEqual(get_role(user, self.studio), Role.ADMIN)
        self.assertEqual(StudioMembership.objects.filter(user=user).count(), 1)

        clear_role_cache(user)
        self.call(user.email, 'zz', '--remove')
        self.assertIsNone(get_role(user, self.studio))

        clear_role_cache(user)
        self.call(user.email, 'zz', 'VIEWER')
        self.assertEqual(get_role(user, self.studio), Role.VIEWER)

    def test_errors(self):
        user = make_user()
        with self.assertRaises(CommandError):
            self.call('missing@example.com', 'zz', 'DJ')
        with self.assertRaises(CommandError):
            self.call(user.email, 'nope', 'DJ')
        with self.assertRaises(CommandError):
            self.call(user.email, 'zz')
