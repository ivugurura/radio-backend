"""Reads the request language from the ``Accept-Language`` header, exposes it as
``request.lang`` and in a context var for the translation catalog."""

from apps.common.translations import normalize_language
from apps.common.translations.state import set_current_language


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = normalize_language(request.headers.get("Accept-Language"))
        request.lang = language
        set_current_language(language)

        response = self.get_response(request)
        response.setdefault("Content-Language", language)
        return response
