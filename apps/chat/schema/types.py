import graphene
from graphene_django import DjangoObjectType

from apps.chat.models import ChatMessage, ChatMute


class ChatMessageType(DjangoObjectType):
    is_hidden = graphene.Boolean()

    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "studio",
            "author_type",
            "author",
            "listener_client_id",
            "listener_display_name",
            "body",
            "quoted_message",
            "created_at",
        )

    def resolve_is_hidden(self, info):
        return self.deleted_at is not None


class ChatMuteType(DjangoObjectType):
    class Meta:
        model = ChatMute
        fields = (
            "id",
            "listener_client_id",
            "reason",
            "expires_at",
            "muted_by",
            "created_at",
        )
