import os


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    from celery import Celery
except ImportError:
    app = None
else:
    app = Celery("ai_business_gurus")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
