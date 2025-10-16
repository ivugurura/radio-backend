from graphene_django import DjangoObjectType

from apps.users.models import User


class UserType(DjangoObjectType):
    class Meta:
        model = User
        fields = ("id", "user_name", "email", "first_name", "last_name", "timezone")
