from datetime import timedelta
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone

from apps.studio.services.helpers import get_studio

from .models import ChatMessage, ChatMute, is_listener_muted

MAX_BODY_LENGTH = 2000


def _serialize_author(user):
    if not user:
        return None
    return {"firstName": user.first_name, "lastName": user.last_name}


def _serialize_message(message: ChatMessage) -> dict:
    quoted = None
    if message.quoted_message_id:
        quoted_message = message.quoted_message
        if quoted_message is not None:
            quoted = {
                "id": str(quoted_message.id),
                "authorType": quoted_message.author_type,
                "author": _serialize_author(quoted_message.author),
                "listenerClientId": quoted_message.listener_client_id,
                "listenerDisplayName": quoted_message.listener_display_name,
                "body": quoted_message.body,
            }

    return {
        "id": str(message.id),
        "authorType": message.author_type,
        "author": _serialize_author(message.author),
        "listenerClientId": message.listener_client_id,
        "listenerDisplayName": message.listener_display_name,
        "body": message.body,
        "quotedMessage": quoted,
        "createdAt": message.created_at.isoformat() if message.created_at else None,
    }


def _get_quoted_message(studio, quoted_message_id):
    if not quoted_message_id:
        return None
    try:
        return ChatMessage.objects.get(id=quoted_message_id, studio=studio)
    except (ChatMessage.DoesNotExist, ValueError, TypeError):
        return None


@transaction.atomic
def _create_message(
    *,
    studio,
    author_type,
    author,
    listener_client_id,
    listener_display_name,
    body,
    quoted_message,
):
    # Passing related objects directly (rather than *_id) keeps them cached on
    # the returned instance, so _serialize_message doesn't trigger extra queries.
    return ChatMessage.objects.create(
        studio=studio,
        author_type=author_type,
        author=author,
        listener_client_id=listener_client_id,
        listener_display_name=listener_display_name,
        body=body,
        quoted_message=quoted_message,
    )


def _hide_message(studio, message_id):
    message = ChatMessage.objects.get(id=message_id, studio=studio)
    message.delete()  # soft delete
    return message


def _unhide_message(studio, message_id):
    message = ChatMessage.all_objects.get(id=message_id, studio=studio)
    message.deleted_at = None
    message.save(update_fields=["deleted_at", "updated_at"])
    return message


def _mute_listener(studio, listener_client_id, reason, expires_at, muted_by):
    mute, _created = ChatMute.objects.update_or_create(
        studio=studio,
        listener_client_id=listener_client_id,
        defaults={
            "reason": reason or "",
            "expires_at": expires_at,
            "muted_by": muted_by,
        },
    )
    return mute


def _unmute_listener(studio, listener_client_id):
    mute = (
        ChatMute.objects.filter(studio=studio, listener_client_id=listener_client_id)
        .order_by("-created_at")
        .first()
    )
    if mute:
        mute.delete()  # soft delete
    return mute


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        studio_slug = self.scope["url_route"]["kwargs"]["studio_slug"]
        studio = await database_sync_to_async(get_studio)(studio_slug)
        if not studio:
            await self.close(code=4004)
            return

        query_params = parse_qs(self.scope.get("query_string", b"").decode("utf-8"))
        listener_client_id = (query_params.get("listener_client_id") or [None])[0]
        display_name = (query_params.get("display_name") or [None])[0]

        self.is_admin = self.scope["user"].is_authenticated

        if not self.is_admin and not listener_client_id:
            await self.close(code=4001)
            return

        self.studio = studio
        self.listener_client_id = listener_client_id or ""
        self.listener_display_name = display_name or ""

        self.group_name = f"chat_studio_{studio.slug}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        if not self.is_admin:
            is_muted = await database_sync_to_async(is_listener_muted)(
                self.studio, self.listener_client_id
            )
            await self.send_json(
                {
                    "type": "connected",
                    "isAdmin": self.is_admin,
                    "listenerClientId": self.listener_client_id,
                    "isMuted": is_muted,
                }
            )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type")

        if message_type == "send_message":
            await self._handle_send_message(content)
        elif message_type == "hide_message":
            await self._handle_hide_message(content)
        elif message_type == "unhide_message":
            await self._handle_unhide_message(content)
        elif message_type == "mute_listener":
            await self._handle_mute_listener(content)
        elif message_type == "unmute_listener":
            await self._handle_unmute_listener(content)
        # Unknown types are ignored.

    async def _handle_send_message(self, content):
        if not self.is_admin:
            display_name = content.get("displayName")
            if display_name:
                self.listener_display_name = display_name

            is_muted = await database_sync_to_async(is_listener_muted)(
                self.studio, self.listener_client_id
            )
            if is_muted:
                await self.send_json({"type": "error", "code": "muted"})
                return

        body = (content.get("body") or "").strip()
        if not body or len(body) > MAX_BODY_LENGTH:
            await self.send_json({"type": "error", "code": "invalid_body"})
            return

        quoted_message = None
        quoted_message_id = content.get("quotedMessageId")
        if quoted_message_id and self.is_admin:
            quoted_message = await database_sync_to_async(_get_quoted_message)(
                self.studio, quoted_message_id
            )

        message = await database_sync_to_async(_create_message)(
            studio=self.studio,
            author_type=(
                ChatMessage.AuthorType.ADMIN
                if self.is_admin
                else ChatMessage.AuthorType.LISTENER
            ),
            author=self.scope["user"] if self.is_admin else None,
            listener_client_id="" if self.is_admin else self.listener_client_id,
            listener_display_name=(
                "" if self.is_admin else self.listener_display_name
            ),
            body=body,
            quoted_message=quoted_message,
        )

        serialized = await database_sync_to_async(_serialize_message)(message)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "payload": {"type": "message_created", "message": serialized},
            },
        )

    async def _handle_hide_message(self, content):
        if not self.is_admin:
            await self.send_json({"type": "error", "code": "forbidden"})
            return

        message_id = content.get("messageId")
        try:
            await database_sync_to_async(_hide_message)(self.studio, message_id)
        except (ChatMessage.DoesNotExist, ValueError, TypeError):
            await self.send_json({"type": "error", "code": "not_found"})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "payload": {"type": "message_hidden", "messageId": message_id},
            },
        )

    async def _handle_unhide_message(self, content):
        if not self.is_admin:
            await self.send_json({"type": "error", "code": "forbidden"})
            return

        message_id = content.get("messageId")
        try:
            await database_sync_to_async(_unhide_message)(self.studio, message_id)
        except (ChatMessage.DoesNotExist, ValueError, TypeError):
            await self.send_json({"type": "error", "code": "not_found"})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "payload": {"type": "message_unhidden", "messageId": message_id},
            },
        )

    async def _handle_mute_listener(self, content):
        if not self.is_admin:
            await self.send_json({"type": "error", "code": "forbidden"})
            return

        listener_client_id = content.get("listenerClientId")
        if not listener_client_id:
            await self.send_json({"type": "error", "code": "invalid_listener"})
            return

        reason = content.get("reason") or ""
        expires_in_minutes = content.get("expiresInMinutes")
        expires_at = (
            timezone.now() + timedelta(minutes=expires_in_minutes)
            if expires_in_minutes
            else None
        )

        mute = await database_sync_to_async(_mute_listener)(
            self.studio,
            listener_client_id,
            reason,
            expires_at,
            self.scope["user"],
        )

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "payload": {
                    "type": "listener_muted",
                    "listenerClientId": listener_client_id,
                    "reason": mute.reason,
                    "expiresAt": (
                        mute.expires_at.isoformat() if mute.expires_at else None
                    ),
                },
            },
        )

    async def _handle_unmute_listener(self, content):
        if not self.is_admin:
            await self.send_json({"type": "error", "code": "forbidden"})
            return

        listener_client_id = content.get("listenerClientId")
        if not listener_client_id:
            await self.send_json({"type": "error", "code": "invalid_listener"})
            return

        await database_sync_to_async(_unmute_listener)(self.studio, listener_client_id)

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat_message",
                "payload": {
                    "type": "listener_unmuted",
                    "listenerClientId": listener_client_id,
                },
            },
        )

    async def chat_message(self, event):
        await self.send_json(event["payload"])
