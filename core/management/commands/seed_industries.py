from django.core.management.base import BaseCommand
from core.models import IndustryTemplate
from core.seed import seed_industries
from core.industry_loader import load_industries

class Command(BaseCommand):
    help = "Seed supported industry templates"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete existing industries before seeding.")

    def handle(self, *args, **kwargs):
        industries, source = load_industries()
        self.stdout.write(f"Industry source: {source}")
        self.stdout.write(f"Templates in source: {len(industries)}")

        if kwargs.get("clear"):
            deleted, _ = IndustryTemplate.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted existing industry records: {deleted}"))

        before = IndustryTemplate.objects.count()
        created, updated, total = seed_industries(stdout=self.stdout)
        after = IndustryTemplate.objects.count()

        self.stdout.write(self.style.SUCCESS("Industry seed complete."))
        self.stdout.write(f"Before: {before}")
        self.stdout.write(f"Created: {created}")
        self.stdout.write(f"Updated: {updated}")
        self.stdout.write(f"After: {after}")

        if after == 0:
            raise RuntimeError("Seed command finished but IndustryTemplate count is still 0.")
