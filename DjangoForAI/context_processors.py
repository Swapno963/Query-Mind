from django.conf import settings


def app_features(request):
    return {
        "app_mode": settings.APP_MODE,
        "chat_enabled": settings.CHAT_ENABLED,
        "api_enabled": settings.API_ENABLED,
        "app_home_url_name": "ask" if settings.CHAT_ENABLED else "developers",
    }
