from django.core.management.base import BaseCommand

from crm.lead_finder import generate_leads_for_batch
from crm.models import LeadGenerationBatch


class Command(BaseCommand):
    help = "Process queued Lead Finder batches. Useful when Celery/Redis is not running."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5, help="Maximum queued batches to process.")

    def handle(self, *args, **options):
        limit = max(options["limit"], 1)
        batches = list(
            LeadGenerationBatch.objects
            .filter(status="queued")
            .order_by("created_at")[:limit]
        )
        for batch in batches:
            self.stdout.write(f"Processing batch #{batch.pk} ({batch.industry}, {batch.quantity_requested})...")
            updated = generate_leads_for_batch(batch.pk)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Batch #{updated.pk}: {updated.status}, "
                    f"{updated.quantity_generated} generated, {updated.duplicates_removed} duplicates removed."
                )
            )
        if not batches:
            self.stdout.write(self.style.SUCCESS("No queued Lead Finder batches."))
