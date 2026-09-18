from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views
from .views_stream import StreamChatViewGraph, RenderMarkdownView

public_urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("team/", views.TeamView.as_view(), name="team"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path(
        "logout/",
        LogoutView.as_view(next_page="landing"),
        name="logout",
    ),
]

onboarding_urlpatterns = [
    path("onboarding/", views.OnboardingView.as_view(), name="onboarding"),
    path(
        "onboarding/discover/",
        views.OnboardingDiscoverView.as_view(),
        name="onboarding_discover",
    ),
]

chat_product_urlpatterns = [
    path("ask/", views.AskView.as_view(), name="ask"),
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

api_portal_urlpatterns = [
    path("developers/", views.DevelopersView.as_view(), name="developers"),
]

urlpatterns = (
    public_urlpatterns
    + onboarding_urlpatterns
    + chat_product_urlpatterns
    + api_portal_urlpatterns
)
