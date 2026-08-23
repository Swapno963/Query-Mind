from django.urls import path

from .views import ChatAPIView, ChatResultAPIView, health_check


urlpatterns = [
    path(
        "chat/",
        ChatAPIView.as_view(),
        name="api-chat",
    ),
    path(
        "chat/result/",
        ChatResultAPIView.as_view(),
        name="api-chat-test",
    ),
    path("health", health_check),
]
