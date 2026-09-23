from django.contrib import admin

from apps.studio.models import StreamingCredential, Studio


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ("display_name", "slug", "is_active", "default_br_kbps")
    search_fields = ("display_name", "slug")


@admin.register(StreamingCredential)
class StreamingCredentialAdmin(admin.ModelAdmin):
    list_display = ("studio", "username", "rotated_at")
    readonly_fields = ("password_encrypted", "rotated_at")
    search_fields = ("studio__slug", "username")
