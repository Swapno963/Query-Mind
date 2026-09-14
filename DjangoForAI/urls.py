from functools import partial

from django.contrib import admin
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("connections.urls")),
    path("", include("chat.urls")),  # Chat becomes the root
    # drf api
    path(
        "api/v1/",
        include("chat.api.urls"),
    ),
    re_path(
        r"^static/(?P<path>.*)$",
        partial(serve_static, insecure=True),
    ),
]
