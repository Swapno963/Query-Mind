from functools import partial

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path

from DjangoForAI.health import health_check
from chat.urls import (
    api_portal_urlpatterns,
    chat_product_urlpatterns,
    onboarding_urlpatterns,
    public_urlpatterns,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health", health_check),
    *public_urlpatterns,
    *onboarding_urlpatterns,
]

if settings.CHAT_ENABLED:
    urlpatterns += [
        *chat_product_urlpatterns,
        path("api/", include("connections.urls")),
    ]

if settings.API_ENABLED:
    urlpatterns += [
        *api_portal_urlpatterns,
        path("api/v1/", include("chat.api.urls")),
    ]

urlpatterns += [
    re_path(
        r"^static/(?P<path>.*)$",
        partial(serve_static, insecure=True),
    ),
]
