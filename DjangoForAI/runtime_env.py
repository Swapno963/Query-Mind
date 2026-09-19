"""Resolve Django SECRET_KEY and DEBUG from the process environment."""

import os

from django.core.exceptions import ImproperlyConfigured

INSECURE_SECRET_PREFIX = "django-insecure-"
INSECURE_SECRET_FALLBACK = (
    "django-insecure-+-_nf=u6gu6%$hqqw@!s9olj^fiody=f(tr6t7*95z3v3&t0(_"
)


def resolve_secret_and_debug(environ=None):
    env = environ if environ is not None else os.environ
    production = (env.get("APP_ENV") or "").strip().lower() == "production"
    secret = (env.get("DJANGO_SECRET_KEY") or env.get("SECRET_KEY") or "").strip()
    if not secret:
        if production:
            raise ImproperlyConfigured(
                "Set DJANGO_SECRET_KEY before running in production."
            )
        secret = INSECURE_SECRET_FALLBACK

    if production:
        debug_raw = env.get("DJANGO_DEBUG") or env.get("DEBUG") or "false"
    else:
        debug_default = "true" if secret.startswith(INSECURE_SECRET_PREFIX) else "false"
        debug_raw = env.get("DJANGO_DEBUG") or env.get("DEBUG") or debug_default
    debug = str(debug_raw).lower() in {"1", "true", "yes"}

    if production or not debug:
        if secret.startswith(INSECURE_SECRET_PREFIX):
            raise ImproperlyConfigured(
                "Set DJANGO_SECRET_KEY before running with DEBUG=False or APP_ENV=production."
            )
    return secret, debug
