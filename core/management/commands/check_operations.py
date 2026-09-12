"""Read-only deployment diagnostics. Never prints credentials or customer content."""
import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from clients.models import AIInstance, Integration
from crm.models import LeadGenerationBatch


class Command(BaseCommand):
    help = "Inspect database, production configuration, and stuck jobs without calling paid providers."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
        parser.add_argument("--strict", action="store_true", help="Fail when a required runtime check fails.")

    def handle(self, *args, **options):
        checks = []
        def add(name, ok, detail, required=False):
            checks.append({"name":name,"ok":bool(ok),"detail":detail,"required":required})
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            add("database",True,"Database connection responds.",True)
        except Exception:
            add("database",False,"Database connection failed.",True)
        add("public_url",settings.PUBLIC_BASE_URL.startswith("https://"),"Production links should use the public HTTPS domain.",not settings.DEBUG)
        add("static_manifest",settings.DEBUG or (settings.STATIC_ROOT/"staticfiles.json").exists(),"Run collectstatic during the production build.",not settings.DEBUG)
        add("email_delivery",settings.EMAIL_BACKEND not in {"django.core.mail.backends.console.EmailBackend","django.core.mail.backends.locmem.EmailBackend","django.core.mail.backends.dummy.EmailBackend"},"Password reset and lead alerts need a delivering email backend.")
        add("platform_ai",bool(settings.PLATFORM_OPENAI_API_KEY),"A configured key enables AI replies; without one the demo uses guided responses.")
        add("stripe",all(value and "placeholder" not in value for value in [settings.STRIPE_SECRET_KEY,settings.STRIPE_WEBHOOK_SECRET]),"Checkout and subscription synchronization require the existing Stripe credentials.")
        for plan in ["STARTER","GROWTH","PRO"]:
            value=getattr(settings,f"STRIPE_PRICE_{plan}","")
            add(f"stripe_{plan.lower()}_price",value and "placeholder" not in value,"Recurring price must be configured for this plan’s checkout button.")
        add("background_queue",bool(settings.CELERY_BROKER_URL),"A running Celery worker must consume the configured broker for searches over 20. This check does not ping the worker.")
        add("public_listings",settings.LEAD_FINDER_ENABLE_PUBLIC_HTTP,"Lead Finder uses real OpenStreetMap listings only.")
        add("upload_storage",str(settings.MEDIA_ROOT) != str(settings.BASE_DIR/"media"),"On Render, keep MEDIA_ROOT on the existing persistent disk; this check cannot verify the mount itself.")
        if checks[0]["ok"]:
            active=AIInstance.objects.filter(client__activation_status="active",status="active")
            channel_count=active.filter(voice_enabled=True).count()+active.filter(sms_enabled=True).count()
            add("twilio_signatures",not channel_count or settings.VALIDATE_TWILIO_SIGNATURES,"Active phone/SMS channels should validate Twilio signatures.",bool(channel_count))
            deadline=timezone.now()-timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT+120)
            stale=LeadGenerationBatch.objects.filter(status__in=["generating","searching","saving"],started_at__lt=deadline).count()
            add("stale_jobs",not stale,f"{stale} jobs exceed the worker time limit. Inspect before recovering them.")
            samples=LeadGenerationBatch.objects.filter(provider_summary__fallback_directory__gt=0).count()
            add("legacy_sample_batches",not samples,f"{samples} older batches contain generated sample data. These records are preserved; their staging rows cannot be promoted into CRM.")
        result={"passed":all(c["ok"] for c in checks if c["required"]),"checks":checks,"provider_calls_made":False}
        if options["json"]:
            self.stdout.write(json.dumps(result,indent=2))
        else:
            for c in checks:self.stdout.write(f"{'OK' if c['ok'] else 'CHECK'}  {c['name']}: {c['detail']}")
        if options["strict"] and not result["passed"]:
            raise CommandError("One or more required runtime checks failed.")
