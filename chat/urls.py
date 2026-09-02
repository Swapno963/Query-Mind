from django.urls import path
from . import views
from .views_stream import StreamChatView, RenderMarkdownView, StreamChatViewGraph

urlpatterns = [
    path("", views.HomepageView.as_view(), name="homepage"),
    path("chat/<int:conversation_id>/", views.ChatView.as_view(), name="chat"),
    path(
        "chat/<int:conversation_id>/stream/",
        StreamChatViewGraph.as_view(),
        name="stream_chat",
    ),
    path(
        "chat/<int:conversation_id>/render-markdown/",
        RenderMarkdownView.as_view(),
        name="render_markdown",
    ),
]
