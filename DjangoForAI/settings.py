"""
Django settings for DjangoForAI project.
"""

from pathlib import Path
import os
import sys

from django.core.exceptions import ImproperlyConfigured

from DjangoForAI.app_mode import api_enabled, chat_enabled, parse_app_mode

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or os.getenv("SECRET_KEY") or (
    "django-insecure-+-_nf=u6gu6%$hqqw@!s9olj^fiody=f(tr6t7*95z3v3&t0(_"
)

debug_default = "true" if SECRET_KEY.startswith("django-insecure-") else "false"
debug_raw = os.getenv("DJANGO_DEBUG") or os.getenv("DEBUG") or debug_default
DEBUG = str(debug_raw).lower() in {"1", "true", "yes"}

allowed_hosts_raw = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_raw.split(",") if host.strip()]

csrf_origins_raw = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in csrf_origins_raw.split(",") if origin.strip()
]
if not CSRF_TRUSTED_ORIGINS:
    for host in ALLOWED_HOSTS:
        if not host or host.startswith(".") or host in {"localhost", "127.0.0.1"}:
            continue
        CSRF_TRUSTED_ORIGINS.append(f"https://{host}")
        if DEBUG:
            CSRF_TRUSTED_ORIGINS.append(f"http://{host}")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

if not DEBUG:
    if SECRET_KEY.startswith("django-insecure-"):
        raise ImproperlyConfigured(
            "Set DJANGO_SECRET_KEY before running with DEBUG=False."
        )
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS must be an explicit host list when DEBUG is False."
        )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chat",
    "connections",
    "rest_framework",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "DjangoForAI.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "DjangoForAI.context_processors.app_features",
            ],
        },
    },
]

WSGI_APPLICATION = "DjangoForAI.wsgi.application"
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "chat.authentication.ApiKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "EXCEPTION_HANDLER": "chat.api.exception_handler.exception_handler",
}

sqlite_path = os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3"))
Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_path,
    },
}

if os.getenv("DB_NAME"):
    DATABASES["client"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", default="127.0.0.1"),
        "PORT": os.getenv("DB_PORT", default="5432"),
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    # {
    #     "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    # },
    # {
    #     "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    # },
    # {
    #     "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    # },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

_running_tests = "test" in sys.argv
APP_MODE = parse_app_mode(
    os.getenv("TEST_APP_MODE", "both") if _running_tests else os.getenv("APP_MODE")
)
CHAT_ENABLED = chat_enabled(APP_MODE)
API_ENABLED = api_enabled(APP_MODE)

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "ask" if CHAT_ENABLED else "developers"
LOGOUT_REDIRECT_URL = "landing"
