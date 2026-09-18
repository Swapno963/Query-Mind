from django.conf import settings

from chat.organizations import organization_for
from chat.product import home_url_name, org_api_enabled, org_chat_enabled


def app_features(request):
    chat = settings.CHAT_ENABLED
    api = settings.API_ENABLED
    home = "ask" if chat else "developers"
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        org = organization_for(user)
        if org is not None:
            chat = org_chat_enabled(org)
            api = org_api_enabled(org)
            home = home_url_name(org)
    return {
        "app_mode": settings.APP_MODE,
        "chat_enabled": chat,
        "api_enabled": api,
        "deployment_chat_enabled": settings.CHAT_ENABLED,
        "deployment_api_enabled": settings.API_ENABLED,
        "app_home_url_name": home,
    }
