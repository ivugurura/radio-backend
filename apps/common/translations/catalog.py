"""
Tiny JSON-backed translation catalog.

Messages are grouped in sections (one JSON file per section, per language):

    apps/common/translations/locales/<lang>/<section>.json

`common` holds shared strings; every other section is feature specific
(`auth`, `medias`, `studio`, ...). This mirrors the frontend i18next namespaces.
"""

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "rw")


@lru_cache(maxsize=None)
def _load_section(language: str, section: str) -> dict:
    path = LOCALES_DIR / language / f"{section}.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def normalize_language(value) -> str:
    """Resolve anything (``en-US``, ``rw``, an Accept-Language list, None) to a
    supported language code, falling back to :data:`DEFAULT_LANGUAGE`."""
    if isinstance(value, str):
        for part in value.split(","):
            tag = part.split(";", 1)[0].strip().lower()
            primary = tag.split("-", 1)[0]
            if primary in SUPPORTED_LANGUAGES:
                return primary
    return DEFAULT_LANGUAGE


def _lookup(mapping: dict, key: str):
    node = mapping
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(key: str, *, language=None, default=None, **params) -> str:
    """Return the message at dotted ``key`` (``"<section>.<key>"``, e.g.
    ``"auth.invalid_credentials"``).

    The language is normally picked up automatically from the current
    request (set by ``apps.common.middleware.LanguageMiddleware``) — pass
    ``language=`` only to override it. Falls back to the default language,
    then to ``default``, then to ``key`` itself. Remaining kwargs are used
    for ``str.format`` interpolation.
    """
    from .state import get_current_language

    section, _, subkey = key.partition(".")
    if not subkey:
        raise ValueError(f"translate() key must be 'section.key', got {key!r}")

    lang = normalize_language(language) if language is not None else get_current_language()

    message = _lookup(_load_section(lang, section), subkey)
    if message is None and lang != DEFAULT_LANGUAGE:
        message = _lookup(_load_section(DEFAULT_LANGUAGE, section), subkey)
    if message is None:
        message = default if default is not None else key

    if params:
        try:
            message = message.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return message
