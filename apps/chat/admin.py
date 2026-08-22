from django.contrib import admin

from .models import ChatMessage, ChatMute


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "studio",
        "author_type",
        "author",
        "listener_display_name",
        "created_at",
        "deleted_at",
    )
    list_filter = ("author_type", "studio")
    search_fields = ("body", "listener_client_id", "listener_display_name")


@admin.register(ChatMute)
class ChatMuteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "studio",
        "listener_client_id",
        "muted_by",
        "expires_at",
        "created_at",
        "deleted_at",
    )
    list_filter = ("studio",)
    search_fields = ("listener_client_id",)
