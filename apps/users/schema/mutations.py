import graphene
import graphql_jwt
from django.contrib.auth import authenticate
from graphql_jwt.shortcuts import get_token

from apps.users.models import User
from apps.users.types.user_types import UserType


class RegisterUser(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)
        display_name = graphene.String(required=False)

    user = graphene.Field(UserType)
    token = graphene.String()
    refresh_token = graphene.String()

    def mutate(self, info, username, password, email, display_name=None):
        if User.objects.filter(username=username).exists():
            raise Exception("Username already taken")

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email,
            display_name=display_name or username,
        )
        # Immediately issue tokens (optional)
        payload = get_token(user)
        refresh = graphql_jwt.shortcuts.create_refresh_token(user)
        return RegisterUser(user=user, token=payload, refresh_token=refresh)


class CustomLogin(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    user = graphene.Field(UserType)
    token = graphene.String()
    refresh_token = graphene.String()

    def mutate(self, info, username, password):
        user = authenticate(username=username, password=password)
        if not user:
            raise Exception("Invalid credentials")
        token = graphql_jwt.shortcuts.get_token(user)
        refresh_token = graphql_jwt.shortcuts.create_refresh_token(user)
        return CustomLogin(user=user, token=token, refresh_token=refresh_token)


class UserMutations(graphene.ObjectType):
    register_user = RegisterUser.Field()
    custom_login = CustomLogin.Field()
