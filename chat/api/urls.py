from django.urls import path

from .views import ChatAPIView


urlpatterns = [
    path(
        "chat/<int:conversation_id>/",
        ChatAPIView.as_view(),
        name="api-chat",
    ),
]
