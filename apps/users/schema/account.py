"""Public account flows: accepting invites and resetting passwords."""

import graphene
from django.conf import settings
from graphql_jwt.shortcuts import create_refresh_token, get_token

from apps.users.schema.admin import AccountLinkPurpose
from apps.users.services import accounts
from apps.users.types.user_types import UserType


class AccountLink(graphene.ObjectType):
    """What a one-time link is for, so the page can greet the right person."""

    valid = graphene.Boolean(required=True)
    purpose = graphene.Field(AccountLinkPurpose)
    email = graphene.String()
    first_name = graphene.String()


class AuthOptions(graphene.ObjectType):
    password_reset_available = graphene.Boolean(
        required=True, description="Self-service reset needs email delivery"
    )


class AccountQuery(graphene.ObjectType):
    account_link = graphene.Field(
        AccountLink, required=True, token=graphene.String(required=True)
    )
    auth_options = graphene.Field(AuthOptions, required=True)

    def resolve_account_link(self, info, token):
        found = accounts.find_token(token)
        if found is None:
            return AccountLink(valid=False)
        return AccountLink(
            valid=True,
            purpose=str(found.purpose),
            email=found.user.email,
            first_name=found.user.first_name,
        )

    def resolve_auth_options(self, info):
        return AuthOptions(password_reset_available=settings.EMAIL_ENABLED)


class SignedIn(graphene.ObjectType):
    token = graphene.String(required=True)
    refresh_token = graphene.String(required=True)
    user = graphene.Field(UserType, required=True)


def _sign_in(user) -> SignedIn:
    return SignedIn(
        token=get_token(user),
        refresh_token=create_refresh_token(user).get_token(),
        user=user,
    )


class AcceptInvite(graphene.Mutation):
    """Set the password of an invited account and sign in."""

    class Arguments:
        token = graphene.String(required=True)
        password = graphene.String(required=True)

    Output = SignedIn

    def mutate(self, info, token, password):
        return _sign_in(accounts.accept_invite(token, password))


class ResetPassword(graphene.Mutation):
    """Set a new password from a reset link. Other sessions are signed out;
    this one is signed in."""

    class Arguments:
        token = graphene.String(required=True)
        new_password = graphene.String(required=True)

    Output = SignedIn

    def mutate(self, info, token, new_password):
        return _sign_in(accounts.reset_password(token, new_password))


class RequestPasswordReset(graphene.Mutation):
    """Email a reset link. Always succeeds, so it can't be used to find out
    which emails have accounts."""

    class Arguments:
        email = graphene.String(required=True)

    ok = graphene.Boolean(required=True)

    def mutate(self, info, email):
        accounts.request_password_reset(email)
        return RequestPasswordReset(ok=True)


class AccountMutations(graphene.ObjectType):
    accept_invite = AcceptInvite.Field()
    reset_password = ResetPassword.Field()
    request_password_reset = RequestPasswordReset.Field()
