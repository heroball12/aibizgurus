from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import DemoSession, DemoCRMLead


class Command(BaseCommand):
    help = "Clear expired demo conversations/fictional CRM records; retain non-content analytics and conversion attribution."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = max(1, options["days"])
        sessions = DemoSession.objects.filter(expires_at__lt=timezone.now() - timedelta(days=days)).exclude(state={})
        count = sessions.count()
        if not options["dry_run"]:
            with transaction.atomic():
                ids = list(sessions.values_list("pk", flat=True))
                DemoCRMLead.objects.filter(session_id__in=ids).delete()
                DemoSession.objects.filter(pk__in=ids).update(state={}, transcript=[], protocol=[], ended_at=timezone.now(), lease=None, busy_until=None)
        self.stdout.write(f"{'Would clear' if options['dry_run'] else 'Cleared'} {count} expired demo conversations. Real CRM data was not touched.")
