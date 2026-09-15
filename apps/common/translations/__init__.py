from .catalog import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    normalize_language,
    translate,
)
from .state import get_current_language, set_current_language

__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "normalize_language",
    "translate",
    "get_current_language",
    "set_current_language",
    "get_language",
]


def get_language(request) -> str:
    """Best-effort language for a request: the value the middleware stored,
    else parsed from the ``Accept-Language`` header."""
    language = getattr(request, "lang", None)
    if language:
        return language
    getter = getattr(request, "headers", None)
    header = getter.get("Accept-Language") if getter is not None else None
    return normalize_language(header)
