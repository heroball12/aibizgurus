from django.core.management.base import BaseCommand
from core.industry_options import get_industry_options

class Command(BaseCommand):
    help = "Show the same industry options the signup page uses"

    def handle(self, *args, **kwargs):
        items, source = get_industry_options()
        self.stdout.write(f"Signup industry count: {len(items)}")
        self.stdout.write(f"Signup industry source: {source}")
        for item in items[:25]:
            self.stdout.write(f"- {item.category}: {item.name} ({item.slug})")
