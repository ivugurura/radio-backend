import graphene
from graphene_django import DjangoObjectType
from apps.medias.models import Track, UploadSession

class TrackType(DjangoObjectType):
    class Meta:
        model = Track
        fields = (
            "id","title","artist","album","genre","state",
            "duration_seconds","bitrate_kbps","processed_rel_path",
            "created_at","updated_at",
        )

class UploadSessionType(DjangoObjectType):
    class Meta:
        model = UploadSession
        fields = ("id", "original_filename", "size_bytes", "mime_type", "finalized", "bytes_received", "created_at", "updated_at")

class TrackConnection(graphene.relay.Connection):
    class Meta:
        node = TrackType
