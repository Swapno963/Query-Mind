from django.conf import settings
from django.http import JsonResponse


def health_check(request):
    return JsonResponse(
        {
            "status": "ok",
            "version": "1.0.0",
            "mode": getattr(settings, "APP_MODE", "both"),
        }
    )
