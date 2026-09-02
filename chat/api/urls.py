from django.urls import path

from .views import ChatAPIView, ChatResultAPIView, health_check, ChatAPIView_GRAPH


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
    path(
        "chat_graph/",
        ChatAPIView_GRAPH.as_view(),
        name="api-chat",
    ),
]
