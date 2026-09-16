from django.core.management.base import BaseCommand

from assistant_ai import concierge


class Command(BaseCommand):
    help = "Prepare Guru's public Runway persona for faster session startup."

    def handle(self, *args, **options):
        if not concierge.is_available():
            self.stdout.write("Guru is not configured; skipping persona sync.")
            return
        try:
            changed = concierge.sync_avatar_defaults()
        except concierge.RunwayError:
            # A provider outage should not take down the website deployment.
            self.stderr.write("Guru persona sync unavailable. Calls will use the current site instructions as an override.")
            return
        self.stdout.write("Guru persona updated." if changed else "Guru persona is up to date.")
