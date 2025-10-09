
from django.db import models

from config.model import BaseModel


class Tag(BaseModel):
    studio = models.ForeignKey("apps.studio.Studio", on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=64)
    is_system = models.BooleanField(default=False)

    class Meta:
        db_table = "tags"
        unique_together = ("studio", "name")
        indexes = [models.Index(fields=["studio", "name"])]

    def __str__(self):
        return self.name

class TrackTag(BaseModel):
    track = models.ForeignKey("apps.media.Track", on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    relevance = models.FloatField(default=1.0)

    class Meta:
        db_table = "track_tags"
        unique_together = ("track", "tag")