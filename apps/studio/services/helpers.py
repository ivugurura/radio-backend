
from apps.studio.models.base import Studio


def get_studio(studio_id: str) -> Studio | None:
    """Return a Studio matched by slug, pk, or code; None if not found.

    Lookup order:
    1. slug field
    2. primary key (pk)
    3. code field
    All exceptions are swallowed; only Studio.DoesNotExist/ValueError expected.
    """
    # Try slug first (never raises)
    studio = Studio.objects.filter(slug=studio_id).first()
    if studio:
        return studio

    # Try primary key (may raise DoesNotExist or ValueError if invalid type)
    try:
        studio = Studio.objects.get(pk=studio_id)
        return studio
    except (Studio.DoesNotExist, ValueError):
        pass

    # Finally try code
    studio = Studio.objects.filter(code=studio_id).first()
    return studio
