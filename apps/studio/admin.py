from django.contrib import admin

from apps.studio.models import StreamingCredential, Studio, StudioMembership


class StudioMembershipInline(admin.TabularInline):
    model = StudioMembership
    fields = ("user", "role", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    extra = 0


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ("display_name", "slug", "is_active", "default_br_kbps")
    search_fields = ("display_name", "slug")
    inlines = (StudioMembershipInline,)


@admin.register(StudioMembership)
class StudioMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "studio", "role", "created_at")
    list_filter = ("studio", "role")
    search_fields = ("user__email", "user__user_name", "studio__slug")
    autocomplete_fields = ("user", "studio")


@admin.register(StreamingCredential)
class StreamingCredentialAdmin(admin.ModelAdmin):
    list_display = ("studio", "username", "rotated_at")
    readonly_fields = ("password_encrypted", "rotated_at")
    search_fields = ("studio__slug", "username")
