from rest_framework.response import Response


def api_error(error_type: str, message: str, status_code: int = 400) -> Response:
    return Response(
        {
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
        },
        status=status_code,
    )
