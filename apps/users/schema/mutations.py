import graphene
import graphql_jwt
from django.contrib.auth import authenticate
from django.db.models import Q
from graphql_jwt.shortcuts import get_token
from rest_framework.authtoken.models import Token

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
            raise Exception("Username already taken")

        user = User.objects.create_user(user_name=user_name, email=email, **kwargs)
        # Immediately issue tokens (optional)
        payload = get_token(user)
        return RegisterUser(user=user, token=payload)


class LoginUser(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)
        password = graphene.String(required=True)

    user = graphene.Field(UserType)
    token = graphene.String()
    rest_token = graphene.String()

    def mutate(self, info, email, password):
        user = authenticate(username=email, password=password)
        if not user:
            raise Exception("Invalid credentials")
        token = graphql_jwt.shortcuts.get_token(user)
        rest_payload = Token.objects.get_or_create(user=user)

        return LoginUser(user=user, token=token, rest_token=rest_payload[0])


class UserMutations(graphene.ObjectType):
    register_user = RegisterUser.Field()
    login_user = LoginUser.Field()
