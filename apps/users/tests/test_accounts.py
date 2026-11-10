import datetime
import json
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from graphql_jwt.refresh_token.utils import get_refresh_token_model
from graphql_jwt.shortcuts import create_refresh_token, get_token

from apps.common.translations import translate
from apps.studio.models import Studio, StudioMembership
from apps.studio.tests.test_permissions import make_user
from apps.users.models import AccountToken, User
from apps.users.tasks import send_account_email
from config.schema import schema

Role = StudioMembership.Role
PASSWORD = 'Str0ng-and-l0ng-pass'
DELAY = 'apps.users.services.accounts.send_account_email.delay'

INVITE = (
    'mutation($email: String!, $first: String, $last: String, $studio: String,'
    ' $role: StudioRole) { inviteUser(email: $email, firstName: $first,'
    ' lastName: $last, studioId: $studio, role: $role)'
    ' { created inviteLink emailed user { email isPending } } }'
)
LINK = (
    'query($token: String!) { accountLink(token: $token)'
    ' { valid purpose email firstName } }'
)
ACCEPT = (
    'mutation($token: String!, $password: String!) { acceptInvite(token: $token,'
    ' password: $password) { token refreshToken user { email } } }'
)
REQUEST_RESET = (
    'mutation($email: String!) { requestPasswordReset(email: $email) { ok } }'
)
RESET = (
    'mutation($token: String!, $password: String!) { resetPassword(token: $token,'
    ' newPassword: $password) { token user { email } } }'
)
SEND_RESET = (
    'mutation($id: UUID!) { sendPasswordReset(userId: $id) { purpose link emailed } }'
)
USERS = (
    'query($search: String, $status: UserStatus) { users(search: $search,'
    ' status: $status) { totalCount items { email status studios { studioId role } }'
    ' } }'
)
UPDATE = (
    'mutation($id: UUID!, $email: String!, $phone: String, $userName: String = "newname")'
    ' { updateUser(userId: $id, firstName: "New", lastName: "Name",'
    ' userName: $userName, email: $email,'
    ' phone: $phone) { user { email firstName phone } } }'
)
SET_ACTIVE = (
    'mutation($id: UUID!, $active: Boolean!) { setUserActive(userId: $id,'
    ' active: $active) { user { status } } }'
)
SIGN_OUT = 'mutation($id: UUID!) { signOutUser(userId: $id) { ok } }'
LOGIN = (
    'mutation($email: String!, $password: String!) { loginUser(email: $email,'
    ' password: $password) { token } }'
)


def run(query, user=None, **variables):
    from django.contrib.auth.models import AnonymousUser

    return schema.execute(
        query,
        variable_values=variables,
        context_value=SimpleNamespace(user=user or AnonymousUser()),
    )


def token_of(link: str) -> str:
    return parse_qs(urlparse(link).query)['token'][0]


def live_refresh_tokens(user) -> int:
    return (
        get_refresh_token_model()
        .objects.filter(user=user, revoked__isnull=True)
        .count()
    )


class AccountTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.studio = Studio.objects.create(slug='zz', display_name='ZZ Radio')
        cls.admin = make_user(is_superuser=True)

    def setUp(self):
        self.admin.refresh_from_db()

    def assertError(self, result, key, **params):
        self.assertIsNotNone(result.errors, 'expected an error')
        self.assertEqual(result.errors[0].message, translate(key, **params))

    def assertOk(self, result):
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def invite(self, actor=None, **variables):
        variables.setdefault('first', 'Ada')
        variables.setdefault('last', 'Lovelace')
        return run(INVITE, actor or self.admin, **variables)


class InviteTests(AccountTestBase):
    def test_superuser_invites_without_studio(self):
        data = self.assertOk(self.invite(email='New.Person@Example.com'))
        result = data['inviteUser']
        self.assertTrue(result['created'])
        self.assertFalse(result['emailed'])  # no SMTP configured in tests
        self.assertTrue(result['inviteLink'].startswith('http'))
        self.assertIn('/accept-invite?token=', result['inviteLink'])
        user = User.objects.get(email='new.person@example.com')
        self.assertTrue(user.is_pending)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.user_name, 'new.person')

    def test_only_raw_token_hash_is_stored(self):
        link = self.assertOk(self.invite(email='a@example.com'))['inviteUser'][
            'inviteLink'
        ]
        raw = token_of(link)
        self.assertFalse(AccountToken.objects.filter(token_hash=raw).exists())
        self.assertEqual(AccountToken.objects.count(), 1)

    def test_studio_admin_must_give_studio(self):
        studio_admin = make_user()
        StudioMembership.objects.create(
            studio=self.studio, user=studio_admin, role=Role.ADMIN
        )
        result = self.invite(actor=studio_admin, email='x@example.com')
        self.assertError(result, 'common.forbidden')

    def test_studio_admin_invites_into_studio(self):
        studio_admin = make_user()
        StudioMembership.objects.create(
            studio=self.studio, user=studio_admin, role=Role.ADMIN
        )
        data = self.assertOk(
            self.invite(
                actor=studio_admin, email='dj@example.com', studio='zz', role='DJ'
            )
        )
        self.assertTrue(data['inviteUser']['user']['isPending'])
        user = User.objects.get(email='dj@example.com')
        self.assertEqual(
            StudioMembership.objects.get(studio=self.studio, user=user).role, Role.DJ
        )

    def test_reinviting_pending_user_replaces_link(self):
        first = self.assertOk(self.invite(email='p@example.com'))['inviteUser']
        second = self.assertOk(
            self.invite(email='p@example.com', studio='zz', role='VIEWER')
        )['inviteUser']
        self.assertFalse(second['created'])
        self.assertIsNotNone(second['inviteLink'])
        old = self.assertOk(run(LINK, token=token_of(first['inviteLink'])))
        self.assertFalse(old['accountLink']['valid'])
        new = self.assertOk(run(LINK, token=token_of(second['inviteLink'])))
        self.assertTrue(new['accountLink']['valid'])

    def test_disabled_account_cannot_be_invited(self):
        disabled = make_user(is_active=False)
        self.assertError(self.invite(email=disabled.email), 'auth.user_disabled')

    @override_settings(EMAIL_ENABLED=True)
    def test_invite_email_is_queued_after_commit(self):
        with mock.patch(DELAY) as delay, self.captureOnCommitCallbacks(execute=True):
            data = self.assertOk(
                self.invite(email='mail@example.com', studio='zz', role='VIEWER')
            )
        self.assertTrue(data['inviteUser']['emailed'])
        to, subject, body = delay.call_args.args
        self.assertEqual(to, 'mail@example.com')
        self.assertIn('ZZ Radio', subject)
        self.assertIn(data['inviteUser']['inviteLink'], body)

    def test_register_user_is_gone(self):
        self.assertNotIn('registerUser', str(schema))


class AcceptInviteTests(AccountTestBase):
    def setUp(self):
        super().setUp()
        link = self.assertOk(self.invite(email='new@example.com'))['inviteUser'][
            'inviteLink'
        ]
        self.token = token_of(link)

    def test_link_describes_invite(self):
        data = self.assertOk(run(LINK, token=self.token))['accountLink']
        self.assertEqual(
            data,
            {
                'valid': True,
                'purpose': 'INVITE',
                'email': 'new@example.com',
                'firstName': 'Ada',
            },
        )
        self.assertFalse(self.assertOk(run(LINK, token='nope'))['accountLink']['valid'])

    def test_pending_user_cannot_sign_in(self):
        result = run(LOGIN, email='new@example.com', password='')
        self.assertError(result, 'auth.invalid_credentials')

    def test_accept_sets_password_signs_in_and_is_single_use(self):
        data = self.assertOk(run(ACCEPT, token=self.token, password=PASSWORD))
        self.assertTrue(data['acceptInvite']['token'])
        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.is_pending)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertOk(run(LOGIN, email='new@example.com', password=PASSWORD))

        again = run(ACCEPT, token=self.token, password=PASSWORD)
        self.assertError(again, 'auth.link_invalid')

    def test_weak_password_is_rejected(self):
        result = run(ACCEPT, token=self.token, password='123')
        self.assertIsNotNone(result.errors)
        self.assertTrue(User.objects.get(email='new@example.com').is_pending)

    def test_expired_link(self):
        AccountToken.objects.update(expires_at=timezone.now() - datetime.timedelta(1))
        self.assertError(
            run(ACCEPT, token=self.token, password=PASSWORD), 'auth.link_invalid'
        )


class PasswordResetTests(AccountTestBase):
    def setUp(self):
        super().setUp()
        self.user = make_user()

    def test_request_does_nothing_without_email(self):
        self.assertOk(run(REQUEST_RESET, email=self.user.email))
        self.assertFalse(AccountToken.objects.exists())
        data = self.assertOk(run('{ authOptions { passwordResetAvailable } }'))
        self.assertFalse(data['authOptions']['passwordResetAvailable'])

    @override_settings(EMAIL_ENABLED=True)
    def test_request_emails_a_link_with_cooldown(self):
        with mock.patch(DELAY) as delay, self.captureOnCommitCallbacks(execute=True):
            self.assertOk(run(REQUEST_RESET, email=self.user.email.upper()))
            self.assertOk(run(REQUEST_RESET, email=self.user.email))  # cooldown
            self.assertOk(run(REQUEST_RESET, email='nobody@example.com'))
        self.assertEqual(delay.call_count, 1)
        self.assertIn('/reset-password?token=', delay.call_args.args[2])

    def test_admin_reset_then_user_resets(self):
        create_refresh_token(self.user)
        data = self.assertOk(run(SEND_RESET, self.admin, id=str(self.user.pk)))
        self.assertEqual(data['sendPasswordReset']['purpose'], 'PASSWORD_RESET')
        raw = token_of(data['sendPasswordReset']['link'])

        result = self.assertOk(run(RESET, token=raw, password=PASSWORD))
        self.assertTrue(result['resetPassword']['token'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        # The old session is gone; only the one just issued is live.
        self.assertEqual(live_refresh_tokens(self.user), 1)
        self.assertError(run(RESET, token=raw, password=PASSWORD), 'auth.link_invalid')

    def test_admin_reset_for_pending_user_reissues_invite(self):
        self.assertOk(self.invite(email='pending@example.com'))
        pending = User.objects.get(email='pending@example.com')
        data = self.assertOk(run(SEND_RESET, self.admin, id=str(pending.pk)))
        self.assertEqual(data['sendPasswordReset']['purpose'], 'INVITE')

    def test_reset_link_cannot_accept_invite(self):
        data = self.assertOk(run(SEND_RESET, self.admin, id=str(self.user.pk)))
        raw = token_of(data['sendPasswordReset']['link'])
        self.assertError(run(ACCEPT, token=raw, password=PASSWORD), 'auth.link_invalid')

    def test_only_superusers_send_resets(self):
        result = run(SEND_RESET, make_user(), id=str(self.user.pk))
        self.assertError(result, 'common.forbidden')

    def test_task_sends_mail(self):
        send_account_email.run('to@example.com', 'Subject', 'Body')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['to@example.com'])


class UserAdminTests(AccountTestBase):
    def test_users_query_lists_filters_and_shows_studios(self):
        dj = make_user()
        StudioMembership.objects.create(studio=self.studio, user=dj, role=Role.DJ)
        make_user(is_active=False)
        self.assertOk(self.invite(email='invited@example.com'))

        everyone = self.assertOk(run(USERS, self.admin))['users']
        self.assertEqual(everyone['totalCount'], 4)
        by_email = {u['email']: u for u in everyone['items']}
        self.assertEqual(
            by_email[dj.email]['studios'], [{'studioId': 'zz', 'role': 'DJ'}]
        )

        for status, count in (('ACTIVE', 2), ('INVITED', 1), ('DISABLED', 1)):
            with self.subTest(status=status):
                data = self.assertOk(run(USERS, self.admin, status=status))
                self.assertEqual(data['users']['totalCount'], count)

        found = self.assertOk(run(USERS, self.admin, search='invited@'))
        self.assertEqual(found['users']['totalCount'], 1)

    def test_users_query_is_superuser_only(self):
        self.assertError(run(USERS, make_user()), 'common.forbidden')
        self.assertIsNotNone(run(USERS).errors)

    def test_update_user(self):
        user = make_user()
        data = self.assertOk(
            run(
                UPDATE,
                self.admin,
                id=str(user.pk),
                email='Changed@Example.com',
                phone=' ',
            )
        )
        self.assertEqual(
            data['updateUser']['user'],
            {'email': 'changed@example.com', 'firstName': 'New', 'phone': None},
        )
        other = make_user()
        result = run(
            UPDATE,
            self.admin,
            id=str(other.pk),
            email='changed@example.com',
            userName='other',
        )
        self.assertError(result, 'auth.email_taken')
        result = run(UPDATE, self.admin, id=str(other.pk), email='o@example.com')
        self.assertError(result, 'auth.username_taken')

    def test_many_users_without_phone(self):
        for email in ('a@example.com', 'b@example.com'):
            self.assertOk(self.invite(email=email))
        self.assertEqual(User.objects.filter(phone__isnull=True).count(), 2)

    def test_disable_and_enable(self):
        user = make_user()
        user.set_password(PASSWORD)
        user.save()
        create_refresh_token(user)
        self.assertOk(run(SEND_RESET, self.admin, id=str(user.pk)))

        data = self.assertOk(run(SET_ACTIVE, self.admin, id=str(user.pk), active=False))
        self.assertEqual(data['setUserActive']['user']['status'], 'DISABLED')
        self.assertEqual(live_refresh_tokens(user), 0)
        self.assertFalse(
            AccountToken.objects.filter(user=user, used_at__isnull=True).exists()
        )
        self.assertError(
            run(LOGIN, email=user.email, password=PASSWORD), 'auth.invalid_credentials'
        )

        data = self.assertOk(run(SET_ACTIVE, self.admin, id=str(user.pk), active=True))
        self.assertEqual(data['setUserActive']['user']['status'], 'ACTIVE')
        self.assertOk(run(LOGIN, email=user.email, password=PASSWORD))

    def test_cannot_disable_self(self):
        result = run(SET_ACTIVE, self.admin, id=str(self.admin.pk), active=False)
        self.assertError(result, 'auth.cannot_change_self')

    def test_disabled_users_token_is_rejected(self):
        user = make_user()
        token = get_token(user)
        User.objects.filter(pk=user.pk).update(is_active=False)
        response = self.client.post(
            '/graphql',
            data=json.dumps({'query': '{ me { email } }'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'RRV {token}',
        )
        body = response.json()
        self.assertFalse((body.get('data') or {}).get('me'))

    def test_sign_out_user(self):
        user = make_user()
        create_refresh_token(user)
        create_refresh_token(user)
        self.assertOk(run(SIGN_OUT, self.admin, id=str(user.pk)))
        self.assertEqual(live_refresh_tokens(user), 0)
        self.assertTrue(User.objects.get(pk=user.pk).is_active)

    def test_login_records_last_login(self):
        user = make_user()
        user.set_password(PASSWORD)
        user.save()
        self.assertOk(run(LOGIN, email=user.email, password=PASSWORD))
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)
