import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from graphql_jwt.exceptions import JSONWebTokenError
from graphql_jwt.shortcuts import get_refresh_token, get_token
from graphql_jwt.utils import get_payload, get_user_by_payload


@method_decorator(csrf_exempt, name='dispatch')
class RefreshTokenView(View):
    """
    API endpoint to refresh JWT access tokens using a valid refresh token.

    POST /api/auth/refresh
    Body: {"refresh_token": "<your_refresh_token>"}

    Returns:
        - 200: New access token
        - 400: Missing refresh token
        - 401: Invalid or expired refresh token
    """

    def post(self, request):
        try:
            # Parse request body
            body = json.loads(request.body.decode('utf-8'))
            refresh_token = body.get('refresh_token')

            if not refresh_token:
                return JsonResponse({
                    'error': 'refresh_token is required'
                }, status=400)

            # Verify and decode the refresh token
            try:
                payload = get_payload(refresh_token)
                user = get_user_by_payload(payload)

                if not user:
                    return JsonResponse({
                        'error': 'Invalid refresh token'
                    }, status=401)

                # Generate new access token
                new_token = get_token(user)

                # Optionally generate new refresh token (if token rotation is enabled)
                new_refresh_token = get_refresh_token(user)

                return JsonResponse({
                    'token': new_token,
                    'refresh_token': new_refresh_token,
                    'user': user
                }, status=200)

            except JSONWebTokenError as e:
                return JsonResponse({
                    'error': f'Invalid or expired refresh token: {str(e)}'
                }, status=401)

        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'An error occurred: {str(e)}'
            }, status=500)


refresh_token_view = RefreshTokenView.as_view()
