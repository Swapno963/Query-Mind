from django.urls import path

from DjangoForAI.health import health_check
from .views import (
    AccessAllowListView,
    AccessRequestView,
    ApiKeyCreateView,
    ChatAPIView,
    ChatAPIView_GRAPH,
    ChatResultAPIView,
    DiscoverIngestView,
    DiscoverInstructionsView,
    MessageResultsView,
    MessagesView,
    ProfileView,
    WorkspaceView,
)


urlpatterns = [
    path("health", health_check),
    path("access-requests/", AccessRequestView.as_view(), name="api-access-requests"),
    path("keys/", ApiKeyCreateView.as_view(), name="api-keys"),
    path("profile/", ProfileView.as_view(), name="api-profile"),
    path(
        "discover/instructions/",
        DiscoverInstructionsView.as_view(),
        name="api-discover-instructions",
    ),
    path("discover/", DiscoverIngestView.as_view(), name="api-discover"),
    path("access/", AccessAllowListView.as_view(), name="api-access"),
    path("workspace/", WorkspaceView.as_view(), name="api-workspace"),
    path("messages/", MessagesView.as_view(), name="api-messages"),
    path("messages/results/", MessageResultsView.as_view(), name="api-message-results"),
    path("chat/", ChatAPIView.as_view(), name="api-chat"),
    path("chat/result/", ChatResultAPIView.as_view(), name="api-chat-test"),
    path("chat_graph/", ChatAPIView_GRAPH.as_view(), name="api-chat-graph"),
]
