from django.contrib import admin

from apps.medias.models import Track, UploadSession


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "studio",
        "original_filename",
        "size_bytes",
        "finalized",
        "bytes_received",
        "created_at",
    )
    list_filter = ("finalized", "studio")
    search_fields = ("original_filename", "id")


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "studio",
        "title",
        "state",
        "bitrate_kbps",
        "duration_seconds",
        "created_at",
    )
    list_filter = ("state", "studio", "is_active")
    search_fields = ("title", "id")
