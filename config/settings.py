import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [x.strip() for x in value.split(",") if x.strip()]


SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
DEBUG = env_bool("DEBUG", default=("RENDER" not in os.environ))

if not DEBUG and (SECRET_KEY in {"dev-change-me", "change-me"} or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("Set a strong SECRET_KEY before running with DEBUG=0.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
render_external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_external_hostname and render_external_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_external_hostname)
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if PUBLIC_BASE_URL.startswith(("http://", "https://")) and PUBLIC_BASE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(PUBLIC_BASE_URL)
if render_external_hostname:
    render_origin = f"https://{render_external_hostname}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "accounts", "core.apps.CoreConfig", "clients", "assistant_ai", "crm", "voice",
    "billing",
    "audit.apps.AuditConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.LegacyPasswordMiddleware",
    "accounts.middleware.AuthRequestLimitMiddleware",
    "audit.middleware.ActivityLogMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "assistant_ai.concierge_middleware.ConciergeFrameMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "600")),
        conn_health_checks=True,
        ssl_require=env_bool(
            "DB_SSL_REQUIRE",
            default=(not DEBUG and DATABASE_URL.startswith(("postgres://", "postgresql://"))),
        ),
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Los_Angeles"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
IS_RUNSERVER_PREVIEW = "runserver" in sys.argv
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or IS_RUNSERVER_PREVIEW
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "portal_home"  # RoleAwareLoginView overrides this for employees/admins.
LOGOUT_REDIRECT_URL = "home"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PLATFORM_OPENAI_API_KEY = os.getenv("PLATFORM_OPENAI_API_KEY", OPENAI_API_KEY)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", OPENAI_MODEL)
OPENAI_CLASSIFICATION_MODEL = os.getenv("OPENAI_CLASSIFICATION_MODEL", "gpt-4o-mini")
OPENAI_REQUEST_TIMEOUT = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "20"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "1"))
OPENAI_DAILY_USAGE_LIMIT = int(os.getenv("OPENAI_DAILY_USAGE_LIMIT", "500"))
AI_SALES_INTELLIGENCE_ENABLED = env_bool("AI_SALES_INTELLIGENCE_ENABLED", default=False)
LEAD_FINDER_ENABLE_PUBLIC_HTTP = env_bool("LEAD_FINDER_ENABLE_PUBLIC_HTTP", default=True)

LEAD_FINDER_PROVIDER_TIMEOUT = float(os.getenv("LEAD_FINDER_PROVIDER_TIMEOUT", "8"))
LEAD_FINDER_OVERPASS_URL = os.getenv("LEAD_FINDER_OVERPASS_URL", "https://overpass-api.de/api/interpreter")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", ""))
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_IGNORE_RESULT = env_bool("CELERY_TASK_IGNORE_RESULT", default=False)
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "540"))

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
VALIDATE_TWILIO_SIGNATURES = env_bool("VALIDATE_TWILIO_SIGNATURES", default=not DEBUG)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@aibusinessgurus.com")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", default=False)

FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "dev-only-change-this-use-fernet-key-in-prod")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_GROWTH = os.getenv("STRIPE_PRICE_GROWTH", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")
OWNER_ALERT_EMAIL = os.getenv("OWNER_ALERT_EMAIL", "")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = env_bool("CSRF_COOKIE_HTTPONLY", default=False)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
X_FRAME_OPTIONS = os.getenv("X_FRAME_OPTIONS", "DENY")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# Optional one-time setup prices are added alongside the recurring plan in Checkout.
STRIPE_SETUP_PRICE_STARTER = os.getenv("STRIPE_SETUP_PRICE_STARTER", "")
STRIPE_SETUP_PRICE_GROWTH = os.getenv("STRIPE_SETUP_PRICE_GROWTH", "")
STRIPE_SETUP_PRICE_PRO = os.getenv("STRIPE_SETUP_PRICE_PRO", "")
DEMO_DAILY_AI_LIMIT = int(os.getenv("DEMO_DAILY_AI_LIMIT", "100"))

# Number of trusted reverse proxies that append to X-Forwarded-For.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1" if "RENDER" in os.environ else "0"))

# Live video concierge. The permanent Runway credential is server-only.
RUNWAYML_API_SECRET = os.getenv("RUNWAYML_API_SECRET", "")
RUNWAY_AVATAR_ID = os.getenv("RUNWAY_AVATAR_ID", "")
VIDEO_CONCIERGE_ENABLED = env_bool("VIDEO_CONCIERGE_ENABLED", default=False)
VIDEO_CONCIERGE_DAILY_LIMIT = int(os.getenv("VIDEO_CONCIERGE_DAILY_LIMIT", "20"))
VIDEO_CONCIERGE_HOURLY_LIMIT = int(os.getenv("VIDEO_CONCIERGE_HOURLY_LIMIT", "3"))
VIDEO_CONCIERGE_MAX_SECONDS = max(60, min(300, int(os.getenv("VIDEO_CONCIERGE_MAX_SECONDS", "300"))))
