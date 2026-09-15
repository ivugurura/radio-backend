"""Per-request current language, kept in a context var so resolvers/services
don't have to thread the request through just to translate a message."""

import contextvars

from .catalog import DEFAULT_LANGUAGE, normalize_language

_current_language: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_language", default=DEFAULT_LANGUAGE
)


def set_current_language(value) -> str:
    language = normalize_language(value)
    _current_language.set(language)
    return language


def get_current_language() -> str:
    return _current_language.get()
