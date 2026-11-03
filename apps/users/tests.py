import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from graphql_jwt.refresh_token.utils import get_refresh_token_model
from graphql_jwt.shortcuts import create_refresh_token
from graphql_jwt.testcases import JSONWebTokenTestCase


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="staff@example.com",
            password="pw",
            user_name="staff",
            phone="+250780000009",
        )

    def post(self, body):
        return self.client.post(
            "/api/auth/logout", data=json.dumps(body), content_type="application/json"
        )

    def test_revokes_refresh_token_so_it_cannot_refresh(self):
        token = create_refresh_token(self.user).get_token()

        self.assertEqual(self.post({"refresh_token": token}).status_code, 204)

        stored = get_refresh_token_model().objects.get(token=token)
        self.assertIsNotNone(stored.revoked)
        refresh = self.client.post(
            "/api/auth/refresh",
            data=json.dumps({"refresh_token": token}),
            content_type="application/json",
        )
        self.assertEqual(refresh.status_code, 401)

    def test_unknown_missing_or_repeated_tokens_still_return_204(self):
        token = create_refresh_token(self.user).get_token()
        self.post({"refresh_token": token})

        for body in ({"refresh_token": token}, {"refresh_token": "nope"}, {}):
            self.assertEqual(self.post(body).status_code, 204)

    def test_does_not_touch_other_sessions(self):
        mine = create_refresh_token(self.user).get_token()
        other_device = create_refresh_token(self.user).get_token()

        self.post({"refresh_token": mine})

        other = get_refresh_token_model().objects.get(token=other_device)
        self.assertIsNone(other.revoked)


UPDATE_PROFILE = """
mutation UpdateProfile(
  $firstName: String!, $lastName: String!, $userName: String!,
  $email: String!, $timezone: String!, $currentPassword: String
) {
  updateProfile(
    firstName: $firstName, lastName: $lastName, userName: $userName,
    email: $email, timezone: $timezone, currentPassword: $currentPassword
  ) { user { email userName firstName timezone } }
}
"""

CHANGE_PASSWORD = """
mutation ChangePassword($currentPassword: String!, $newPassword: String!) {
  changePassword(currentPassword: $currentPassword, newPassword: $newPassword) {
    token refreshToken
  }
}
"""


class ProfileAndPasswordTests(JSONWebTokenTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="staff@example.com",
            password="old-pass-1234",
            user_name="staff",
            phone="+250780000001",
            first_name="Old",
            last_name="Name",
        )
        get_user_model().objects.create_user(
            email="taken@example.com",
            password="x",
            user_name="taken",
            phone="+250780000002",
            first_name="A",
            last_name="B",
        )
        self.client.authenticate(self.user)

    def profile(self, **overrides):
        variables = {
            "firstName": "New",
            "lastName": "Name",
            "userName": "staff",
            "email": "staff@example.com",
            "timezone": "Africa/Kigali",
            **overrides,
        }
        return self.client.execute(UPDATE_PROFILE, variables)

    def test_updates_names_and_timezone_without_password(self):
        res = self.profile()

        self.assertIsNone(res.errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "New")
        self.assertEqual(self.user.timezone, "Africa/Kigali")

    def test_email_change_needs_correct_current_password(self):
        self.assertIsNotNone(self.profile(email="new@example.com").errors)
        self.assertIsNotNone(
            self.profile(email="new@example.com", currentPassword="wrong").errors
        )

        res = self.profile(email="New@Example.com", currentPassword="old-pass-1234")

        self.assertIsNone(res.errors)
        self.assertEqual(res.data["updateProfile"]["user"]["email"], "new@example.com")

    def test_rejects_taken_email_username_and_bad_timezone(self):
        for overrides in (
            {"email": "taken@example.com", "currentPassword": "old-pass-1234"},
            {"userName": "TAKEN"},
            {"timezone": "Mars/Olympus"},
            {"firstName": "  "},
        ):
            self.assertIsNotNone(self.profile(**overrides).errors, overrides)

    def test_change_password_revokes_other_sessions(self):
        other_device = create_refresh_token(self.user).get_token()

        res = self.client.execute(
            CHANGE_PASSWORD,
            {"currentPassword": "old-pass-1234", "newPassword": "N3w-radio-pass!"},
        )

        self.assertIsNone(res.errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("N3w-radio-pass!"))
        tokens = get_refresh_token_model().objects
        self.assertIsNotNone(tokens.get(token=other_device).revoked)
        fresh = res.data["changePassword"]["refreshToken"]
        self.assertIsNone(tokens.get(token=fresh).revoked)

    def test_change_password_checks_current_and_strength(self):
        wrong = self.client.execute(
            CHANGE_PASSWORD,
            {"currentPassword": "nope", "newPassword": "N3w-radio-pass!"},
        )
        weak = self.client.execute(
            CHANGE_PASSWORD, {"currentPassword": "old-pass-1234", "newPassword": "123"}
        )

        self.assertIsNotNone(wrong.errors)
        self.assertIsNotNone(weak.errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-1234"))
