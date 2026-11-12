from django.contrib import admin

from apps.users.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Read-mostly listing; it exists so membership forms can autocomplete users."""

    list_display = ("email", "user_name", "first_name", "last_name", "is_active")
    list_filter = ("is_active", "is_superuser")
    search_fields = ("email", "user_name", "first_name", "last_name")
    exclude = ("password", "previous_passwords", "groups", "user_permissions")
    readonly_fields = ("last_login", "created_at", "updated_at")
