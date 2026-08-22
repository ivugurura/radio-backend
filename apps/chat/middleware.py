from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from graphql_jwt.exceptions import JSONWebTokenError
from graphql_jwt.shortcuts import get_user_by_payload
from graphql_jwt.utils import jwt_decode


@database_sync_to_async
def _get_user_from_token(token: str):
    try:
        payload = jwt_decode(token)
        return get_user_by_payload(payload)
    except JSONWebTokenError:
        return AnonymousUser()
    except Exception:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """ASGI middleware that authenticates websocket connections using the
    existing GraphQL JWT infrastructure, reading the token from the
    ``token`` query-string parameter.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"")
        query_params = parse_qs(query_string.decode("utf-8"))
        token = (query_params.get("token") or [None])[0]

        if token:
            scope["user"] = await _get_user_from_token(token)
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
