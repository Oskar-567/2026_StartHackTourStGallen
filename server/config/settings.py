"""Django settings.

Every environment-specific value comes from an environment variable. Locally they are
loaded from server/.env (see .env.example); on Render they are set by render.yaml.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Existing environment variables (CI, Render) take precedence over the .env file.
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DEBUG")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
if render_hostname := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_hostname)

# Render terminates TLS at its proxy and forwards the original scheme in this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://app:app@127.0.0.1:5433/app",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MAILERS = {
    "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")

# Viseca "Agent on a Leash" challenge API (server/viseca/, api/services.py) and the
# local challenge data pack (server/api/management/commands/replay.py). The worker
# and mandate-lifecycle views need the first two; replay.py only needs the third and
# never uses the API key or the network.
VISECA_BASE_URL = os.environ.get("VISECA_BASE_URL", "")
VISECA_API_KEY = os.environ.get("VISECA_API_KEY", "")
VISECA_DATA_DIR = os.environ.get("VISECA_DATA_DIR", "")

# Fact extraction (server/facts/). Which backend reads merchant product text:
# "stand-in" (no model), "local" (Ollama on this machine), "hosted" (Anthropic API).
# Swapping backends is an env change, never a code change -- see facts/__init__.py.
FACTS_BACKEND = os.environ.get("FACTS_BACKEND", "stand-in")
# Must leave the worker's watchdog (2s before the deadline) room to act.
FACTS_TIMEOUT_SECONDS = float(os.environ.get("FACTS_TIMEOUT_SECONDS", "4"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
# Reasoning models think before answering. For a one-sentence extraction that is
# pure latency against an 8s deadline, so it is off unless deliberately enabled.
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "false").lower() in ("1", "true", "yes")
FACTS_MODEL = os.environ.get("FACTS_MODEL", "claude-haiku-4-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Hackathon API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
