from zoneinfo import available_timezones

import graphene
import graphql_jwt
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now as timezone_now
from graphql_jwt.decorators import login_required
from graphql_jwt.refresh_token.utils import get_refresh_token_model
from graphql_jwt.shortcuts import create_refresh_token, get_token
from rest_framework.authtoken.models import Token

from apps.common.translations import translate
from apps.users.models import User
from apps.users.types.user_types import UserType


class RegisterUser(graphene.Mutation):
    class Arguments:
        user_name = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)
        first_name = graphene.String(required=True)
        last_name = graphene.String(required=True)
        display_name = graphene.String(required=False)
        phone = graphene.String(required=False)
        profile_picture = graphene.String(required=False)

    user = graphene.Field(UserType)
    token = graphene.String()

    def mutate(self, info, user_name, email, **kwargs):
        if User.objects.filter(Q(user_name=user_name) | Q(email=email)).exists():
            raise Exception(translate("auth.username_taken"))

        user = User.objects.create_user(user_name=user_name, email=email, **kwargs)
        payload = get_token(user)
        return RegisterUser(user=user, token=payload)


class LoginUser(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)
        password = graphene.String(required=True)

    user = graphene.Field(UserType)
    token = graphene.String()
    refresh_token = graphene.String()
    rest_token = graphene.String()

    def mutate(self, info, email, password):
        user = authenticate(username=email, password=password)
        if not user:
            raise Exception(translate("auth.invalid_credentials"))
        token = graphql_jwt.shortcuts.get_token(user)
        rest_payload = Token.objects.get_or_create(user=user)

        return LoginUser(
            user=user,
            token=token,
            refresh_token=create_refresh_token(user).get_token(),
            rest_token=rest_payload[0],
        )


class UpdateProfile(graphene.Mutation):
    """Edit the signed-in user's own details. Changing the email address, which
    is the login, also requires the current password."""

    class Arguments:
        first_name = graphene.String(required=True)
        last_name = graphene.String(required=True)
        user_name = graphene.String(required=True)
        email = graphene.String(required=True)
        timezone = graphene.String(required=True)
        current_password = graphene.String(required=False)

    user = graphene.Field(UserType)

    @login_required
    def mutate(
        self,
        info,
        first_name,
        last_name,
        user_name,
        email,
        timezone,
        current_password=None,
    ):
        user = info.context.user
        first_name, last_name = first_name.strip(), last_name.strip()
        user_name = user_name.strip()
        email = User.objects.normalize_email(email.strip()).lower()

        if not first_name or not last_name:
            raise Exception(translate("auth.name_required"))
        if not user_name:
            raise Exception(translate("auth.username_required"))
        try:
            validate_email(email)
        except ValidationError:
            raise Exception(translate("auth.invalid_email"))
        if timezone not in available_timezones():
            raise Exception(translate("auth.invalid_timezone"))

        others = User.objects.exclude(pk=user.pk)
        if others.filter(user_name__iexact=user_name).exists():
            raise Exception(translate("auth.username_taken"))
        if email != user.email.lower():
            if not current_password:
                raise Exception(translate("auth.current_password_required"))
            if not user.check_password(current_password):
                raise Exception(translate("auth.current_password_incorrect"))
            if others.filter(email__iexact=email).exists():
                raise Exception(translate("auth.email_taken"))

        user.first_name = first_name
        user.last_name = last_name
        user.user_name = user_name
        user.email = email
        user.timezone = timezone
        user.save(
            update_fields=[
                "first_name",
                "last_name",
                "user_name",
                "email",
                "timezone",
                "updated_at",
            ]
        )
        return UpdateProfile(user=user)


class ChangePassword(graphene.Mutation):
    """
    Change the signed-in user's password and sign out every other session:
    all refresh tokens and the REST token are revoked, and a fresh token pair
    is returned so this browser stays signed in.
    """

    class Arguments:
        current_password = graphene.String(required=True)
        new_password = graphene.String(required=True)

    token = graphene.String()
    refresh_token = graphene.String()

    @login_required
    def mutate(self, info, current_password, new_password):
        user = info.context.user
        if not user.check_password(current_password):
            raise Exception(translate("auth.current_password_incorrect"))
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            raise Exception(" ".join(exc.messages))

        with transaction.atomic():
            user.set_password(new_password)
            user.save(update_fields=["password", "updated_at"])
            get_refresh_token_model().objects.filter(
                user=user, revoked__isnull=True
            ).update(revoked=timezone_now())
            Token.objects.filter(user=user).delete()

        return ChangePassword(
            token=get_token(user),
            refresh_token=create_refresh_token(user).get_token(),
        )


class UserMutations(graphene.ObjectType):
    register_user = RegisterUser.Field()
    login_user = LoginUser.Field()
    update_profile = UpdateProfile.Field()
    change_password = ChangePassword.Field()
