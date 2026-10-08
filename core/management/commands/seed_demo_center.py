from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import DemoExperience, DemoRevision
from core.experience.data import VERSION, seed_content


class Command(BaseCommand):
    help = "Seed the isolated Velocity Motors demo. Never writes real client/CRM data."

    def add_arguments(self, parser):
        parser.add_argument("--publish", action="store_true", help="Explicitly publish this demo for public visitors.")
        parser.add_argument("--restore-seed", action="store_true", help="Point new sessions at the seeded version; historical sessions keep their version.")

    @transaction.atomic
    def handle(self, *args, **options):
        demo, _ = DemoExperience.objects.get_or_create(slug="automotive", defaults={"name": "Velocity Motors", "profile_slug": "automotive"})
        revision, _ = DemoRevision.objects.get_or_create(experience=demo, version=VERSION, defaults={"content": seed_content()})
        if not demo.current_revision_id or options["restore_seed"] or demo.current_revision.version in ("velocity-2026.1.1", "velocity-2026.1.2"):
            demo.current_revision = revision
        if options["publish"]:
            demo.published = True
        demo.save()
        self.stdout.write(self.style.SUCCESS(f"Velocity Motors: {len(revision.content['inventory'])} synthetic vehicles, 10 scenarios. {'Published' if demo.published else 'Draft'}. No CRM data created."))
