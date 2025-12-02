"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView

from apps.medias.views import serve_track, upload_chunk_view
from apps.studio.api.ingest import ingest_listener_events
from apps.studio.api.play_ingest import ingest_play_events
from apps.studio.views import studio_playlist

urlpatterns = [
    path("admin/", admin.site.urls),
    # Enable GraphiQL in dev
    path("graphql", csrf_exempt(GraphQLView.as_view(graphiql=True))),
    # API endpoints
    path("api/uploads/<uuid:upload_id>/chunk",
         upload_chunk_view, name="upload-chunk"),
    path(
        "api/studios/<str:studio_slug>/playlist",
        studio_playlist,
        name="studio-playlist",
    ),
    path(
        "api/studios/<str:studio_slug>/listener-events",
        ingest_listener_events,
        name="studio-listener-events",
    ),
    path(
        "api/studios/<str:studio_slug>/play-events",
        ingest_play_events,
        name="studio-play-events",
    ),
    path("api/studios/<str:studio_slug>/tracks/<str:track_id>",
         serve_track, name="serve-track"),
]
