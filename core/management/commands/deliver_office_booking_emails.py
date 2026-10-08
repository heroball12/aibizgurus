from django.core.management.base import BaseCommand, CommandError

from core.booking import deliver_emails, email_ready
from core.booking_models import OfficeBookingEmail


class Command(BaseCommand):
    help = "Retry pending office booking notifications through the configured mail backend."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        if not email_ready():
            raise CommandError("Configure a delivery email backend before retrying notifications.")
        if not 1 <= options["limit"] <= 100:
            raise CommandError("Limit must be between 1 and 100.")
        deliver_emails(limit=options["limit"])
        pending = OfficeBookingEmail.objects.filter(delivered_at__isnull=True).exclude(
            appointment__status="canceled", kind__startswith="confirmed"
        ).count()
        self.stdout.write(f"Delivery pass completed. {pending} active notifications remain pending.")
