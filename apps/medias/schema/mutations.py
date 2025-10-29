import hashlib

import graphene
from django.db import transaction
from graphql_jwt.decorators import login_required

from apps.medias.models import UploadSession, Track
from apps.medias.services.delete import delete_track_files
from apps.medias.services.upload import init_upload, ensure_upload_token, finalize_upload
from apps.studio.models import Studio
from apps.medias.tasks import start_pipeline_for_upload
import logging


logger = logging.getLogger(__name__)


class RequestUpload(graphene.Mutation):
    class Arguments:
        studio_slug = graphene.String(required=True)
        file_name = graphene.String(required=True)
        size_bytes = graphene.Int(required=True)
        mime_type = graphene.String(required=True)
        checksum_sha256 = graphene.String(required=False)

    upload_id = graphene.UUID()
    chunk_url = graphene.String()
    upload_token = graphene.String()
    track_id = graphene.UUID()

    @staticmethod
    @transaction.atomic
    @login_required
    def mutate(self, info, studio_slug, file_name, size_bytes, mime_type, checksum_sha256=None):
        user = info.context.user
        studio = Studio.objects.get(slug=studio_slug, is_active=True)

        up = UploadSession.objects.create(
            studio=studio,
            original_filename=file_name,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )
        track = Track.objects.create(
            studio=studio,
            title=file_name,
            state=Track.State.UPLOADING,
            content_hash=checksum_sha256 or hashlib.sha256(
                f"{up.id}:{file_name}".encode()).hexdigest(),
            upload_session=up,
        )
        init_upload(studio, up)
        token = ensure_upload_token(up)
        chunk_url = f"/api/uploads/{up.id}/chunk"
        return RequestUpload(
            upload_id=up.id,
            chunk_url=chunk_url,
            upload_token=token,
            track_id=track.id,
        )


class FinalizeUpload(graphene.Mutation):
    class Arguments:
        upload_id = graphene.UUID(required=True)
        checksum_sha256 = graphene.String(required=False)

    ok = graphene.Boolean()
    track_id = graphene.UUID()

    @staticmethod
    @transaction.atomic
    @login_required
    def mutate(self, info, upload_id, checksum_sha256=None):
        user = info.context.user
        upload = UploadSession.objects.select_for_update().get(id=upload_id)
        track = Track.objects.get(upload_session=upload)

        finalize_upload(upload)
        upload.finalized = True
        upload.save(update_fields=["finalized", "updated_at"])
        logger.info("Finalizing upload %s; scheduling start_pipeline_for_upload for track %s", upload.id, track.id)
        start_pipeline_for_upload.delay(track.id)
        logger.info("Called start_pipeline_for_upload.delay for %s", track.id)
        return FinalizeUpload(ok=True, track_id=track.id)


class DeleteTrack(graphene.Mutation):
    class Arguments:
        track_id = graphene.UUID(required=True)

    ok = graphene.Boolean()

    @classmethod
    @transaction.atomic
    @login_required
    def mutate(cls, root, info, track_id):
        user = info.context.user
        if not user or not user.is_authenticated:
            raise Exception("auth required")

        try:
            track = Track.objects.select_related("studio", "upload_session").get(id=track_id)
        except Track.DoesNotExist:
            # idempotent OK (already deleted)
            return DeleteTrack(ok=True)

        # TODO: permission check (user can manage track in this studio)

        # Remove files first (best effort)
        delete_track_files(track)

        # Optionally delete the related UploadSession to clean up database (if you prefer to keep history, remove this)
        up = track.upload_session
        track.delete()

        if up:
            # If no other tracks refer to this session, delete it
            if not UploadSession.objects.filter(id=up.id).exists():
                try:
                    up.delete()
                except Exception:
                    pass

        return DeleteTrack(ok=True)


class MediasMutations(graphene.ObjectType):
    request_upload = RequestUpload.Field()
    finalize_upload = FinalizeUpload.Field()
    delete_track = DeleteTrack.Field()
