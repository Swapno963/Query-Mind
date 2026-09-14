from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        error_type = "authentication_error"
    elif isinstance(exc, PermissionDenied):
        error_type = "permission_error"
    else:
        error_type = "invalid_request_error"
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        message = "; ".join(f"{key}: {value}" for key, value in detail.items())
    elif isinstance(detail, list):
        message = "; ".join(str(item) for item in detail)
    else:
        message = str(detail or exc)
    response.data = {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
    }
    return response
