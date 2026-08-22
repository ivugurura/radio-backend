from django.urls import re_path

from .consumers import ChatConsumer

websocket_urlpatterns = [
    re_path(r"^ws/studios/(?P<studio_slug>[\w-]+)/chat/$", ChatConsumer.as_asgi()),
]
