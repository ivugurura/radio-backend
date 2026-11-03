import json

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView
from graphql_jwt.exceptions import JSONWebTokenExpired
from graphql_jwt.refresh_token.utils import get_refresh_token_model
from graphql_jwt.shortcuts import create_refresh_token, get_token

from apps.common.translations import translate


def _session_expired(status):
    return JsonResponse({'error': translate('auth.session_expired')}, status=status)


class AuthAwareGraphQLView(GraphQLView):
    """Marks expired access tokens so the UI refreshes instead of showing an error."""

    @staticmethod
    def format_error(error):
        formatted = GraphQLView.format_error(error)
        if isinstance(getattr(error, 'original_error', None), JSONWebTokenExpired):
            formatted['extensions'] = {
                **formatted.get('extensions', {}),
                'code': 'UNAUTHENTICATED',
            }
        return formatted


@method_decorator(csrf_exempt, name='dispatch')
class RefreshTokenView(View):
    """
    API endpoint to exchange a refresh token for a new access and refresh token.
    The submitted refresh token is revoked, so each one works only once.

    POST /api/auth/refresh
    Body: {"refresh_token": "<your_refresh_token>"}

    Returns:
        - 200: {"token": "<access_token>", "refresh_token": "<refresh_token>"}
        - 400: Missing refresh token
        - 401: Invalid, revoked or expired refresh token
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except ValueError:
            body = None

        token = body.get('refresh_token') if isinstance(body, dict) else None
        if not token or not isinstance(token, str):
            return _session_expired(status=400)

        # Lock the row so concurrent requests can't both rotate the same token.
        refresh_token = (
            get_refresh_token_model()
            .objects.select_for_update(of=('self',))
            .select_related('user')
            .filter(token=token, revoked__isnull=True)
            .first()
        )
        if (
            refresh_token is None
            or refresh_token.is_expired(request)
            or not refresh_token.user.is_active
        ):
            return _session_expired(status=401)

        user = refresh_token.user
        refresh_token.revoke(request)

        return JsonResponse(
            {
                'token': get_token(user),
                'refresh_token': create_refresh_token(user).get_token(),
            }
        )


refresh_token_view = RefreshTokenView.as_view()


@method_decorator(csrf_exempt, name='dispatch')
class LogoutView(View):
    """
    API endpoint to end a session by revoking its refresh token, so a copied
    token can't mint new access tokens after sign-out. Access tokens are
    stateless and simply expire (JWT_EXPIRATION_DELTA).

    POST /api/auth/logout
    Body: {"refresh_token": "<your_refresh_token>"}

    Returns 204 whether or not the token was live, so the response doesn't
    reveal which tokens exist and signing out twice is harmless.
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except ValueError:
            body = None

        token = body.get('refresh_token') if isinstance(body, dict) else None
        if isinstance(token, str) and token:
            refresh_token = (
                get_refresh_token_model()
                .objects.filter(token=token, revoked__isnull=True)
                .first()
            )
            if refresh_token is not None:
                refresh_token.revoke(request)

        return HttpResponse(status=204)


logout_view = LogoutView.as_view()
