from django.urls import path

from .views import ChatAPIView, ChatResultAPIView


urlpatterns = [
    path(
        "chat/",
        ChatAPIView.as_view(),
        name="api-chat",
    ),
    path(
        "chat/result/",
        ChatResultAPIView.as_view(),
        name="api-chat-bot",
    ),
]
