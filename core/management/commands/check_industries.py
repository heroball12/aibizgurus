from django.core.management.base import BaseCommand
from core.models import IndustryTemplate

class Command(BaseCommand):
    help = "Show industry template count and sample records"

    def handle(self, *args, **kwargs):
        qs = IndustryTemplate.objects.order_by("category", "name")
        self.stdout.write(f"Industry count: {qs.count()}")
        for item in qs[:20]:
            self.stdout.write(f"- {item.category}: {item.name} ({item.slug})")
