"""API / MCP key request, approval state, and password-gated copy."""

from __future__ import annotations

from django.contrib.auth import authenticate
from django.http import JsonResponse

from chat.api_keys import generate_api_key, user_has_approved_api_access
from chat.models import ApiAccessRequest, ApiKey
from chat.organizations import organization_for

SESSION_PENDING_KEY = "pending_api_key"


def _wants_json(request) -> bool:
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


def latest_access_request(user, kind: str) -> ApiAccessRequest | None:
    if not user or not user.is_authenticated:
        return None
    return user.api_access_requests.filter(kind=kind).order_by("-created_at").first()


def portal_context(request, kind: str) -> dict:
    latest = latest_access_request(request.user, kind)
    approved = user_has_approved_api_access(request.user, kind=kind)
    keys = [
        {
            "id": key.id,
            "masked": f"{key.prefix}••••",
        }
        for key in request.user.api_keys.filter(revoked_at__isnull=True)
    ]
    return {
        "key_kind": kind,
        "api_status": latest.status if latest else "none",
        "api_approved": approved,
        "api_keys": keys,
        "can_copy_key": approved,
        "revealed_api_key": request.session.pop("revealed_api_key", None),
    }


def create_access_request(user, kind: str, note: str = "") -> ApiAccessRequest:
    if user_has_approved_api_access(user, kind=kind):
        existing = latest_access_request(user, kind)
        if existing and existing.status == ApiAccessRequest.STATUS_APPROVED:
            return existing
    pending = user.api_access_requests.filter(
        kind=kind, status=ApiAccessRequest.STATUS_PENDING
    ).first()
    if pending:
        return pending
    return ApiAccessRequest.objects.create(
        user=user,
        kind=kind,
        note=(note or "").strip(),
    )


def handle_key_portal_post(request, kind: str):
    action = request.POST.get("action")
    if action == "request":
        if user_has_approved_api_access(request.user, kind=kind):
            message = _already_approved_message(kind)
            level = "success"
        elif request.user.api_access_requests.filter(
            kind=kind, status=ApiAccessRequest.STATUS_PENDING
        ).exists():
            message = _waiting_message(kind)
            level = "info"
        else:
            create_access_request(
                request.user, kind, request.POST.get("note") or ""
            )
            message = _requested_message(kind)
            level = "success"
        if _wants_json(request):
            latest = latest_access_request(request.user, kind)
            return JsonResponse(
                {
                    "ok": True,
                    "status": latest.status if latest else "none",
                    "message": message,
                }
            )
        return {"message": message, "level": level}

    if action == "copy_key":
        return _copy_key(request, kind)
    return None


def _copy_key(request, kind: str):
    password = request.POST.get("password") or ""
    confirmed = authenticate(
        request, username=request.user.username, password=password
    )
    if confirmed is None or confirmed.pk != request.user.pk:
        error = "That password did not match."
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        return {"message": error, "level": "error"}

    if not user_has_approved_api_access(request.user, kind=kind):
        error = _not_approved_message(kind)
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": error}, status=403)
        return {"message": error, "level": "error"}

    if organization_for(request.user) is None:
        error = (
            "Keys must belong to an organization admin. "
            "Create or sign in as that org user, then mint the key there."
        )
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": error}, status=400)
        return {"message": error, "level": "error"}

    raw = _secret_for_copy(request, kind)
    if _wants_json(request):
        request.session.pop("revealed_api_key", None)
        return JsonResponse(
            {
                "ok": True,
                "key": raw,
                "message": "Key copied. QueryMind will not show this secret again.",
            }
        )
    request.session["revealed_api_key"] = raw
    return {
        "message": "Copy this key now. QueryMind will not show it again.",
        "level": "success",
        "revealed": raw,
    }


def _secret_for_copy(request, kind: str) -> str:
    raw, prefix, hashed = generate_api_key()
    ApiKey.objects.create(user=request.user, prefix=prefix, key_hash=hashed)
    request.session.pop(SESSION_PENDING_KEY, None)
    return raw


def _already_approved_message(kind: str) -> str:
    label = "MCP" if kind == ApiAccessRequest.KIND_MCP else "API"
    return f"{label} access is already approved."


def _waiting_message(kind: str) -> str:
    label = "MCP" if kind == ApiAccessRequest.KIND_MCP else "API"
    return f"Your {label} key request is waiting for approval."


def _requested_message(kind: str) -> str:
    label = "MCP" if kind == ApiAccessRequest.KIND_MCP else "API"
    return f"Request sent. A QueryMind admin must approve your {label} key."


def _not_approved_message(kind: str) -> str:
    label = "MCP" if kind == ApiAccessRequest.KIND_MCP else "API"
    return f"Your {label} key request has not been approved yet."
