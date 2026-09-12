from django.urls import path
from . import views
from .views_stream import StreamChatView, RenderMarkdownView, StreamChatViewGraph

urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("ask/", views.AskView.as_view(), name="ask"),
    path("onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    path("data/", views.DataAccessView.as_view(), name="data_access"),
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
