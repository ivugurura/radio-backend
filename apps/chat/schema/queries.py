import graphene
from django.db.models import Q
from django.utils import timezone

from apps.chat.models import ChatMessage, ChatMute
from apps.chat.schema.types import ChatMessageType, ChatMuteType
from apps.studio.services.helpers import get_studio


class ChatQuery(graphene.ObjectType):
    chat_messages = graphene.List(
        graphene.NonNull(ChatMessageType),
        studio_slug=graphene.String(required=True),
        before=graphene.DateTime(),
        limit=graphene.Int(default_value=30),
    )
    chat_mutes = graphene.List(
        graphene.NonNull(ChatMuteType),
        studio_slug=graphene.String(required=True),
    )

    def resolve_chat_messages(self, info, studio_slug, before=None, limit=30):
        studio = get_studio(studio_slug)
        if not studio:
            return []

        manager = (
            ChatMessage.all_objects
            if info.context.user.is_authenticated
            else ChatMessage.objects
        )
        qs = manager.filter(studio=studio)
        if before:
            qs = qs.filter(created_at__lt=before)

        messages = list(qs.order_by("-created_at")[:limit])
        return list(reversed(messages))

    def resolve_chat_mutes(self, info, studio_slug):
        if not info.context.user.is_authenticated:
            return []

        studio = get_studio(studio_slug)
        if not studio:
            return []

        now = timezone.now()
        return ChatMute.objects.filter(studio=studio).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        ).order_by("-created_at")
