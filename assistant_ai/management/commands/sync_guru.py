import base64
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant_ai import concierge


class Command(BaseCommand):
    help = "Prepare Guru's public Runway persona for faster session startup."

    def add_arguments(self, parser):
        parser.add_argument("--helmet", action="store_true", help="Replace Guru's reference portrait with the sealed helmet design. Run once after an appearance change.")

    def handle(self, *args, **options):
        if not concierge.is_available():
            self.stdout.write("Guru is not configured; skipping persona sync.")
            return
        try:
            changed = concierge.sync_avatar_defaults()
            if options["helmet"]:
                portrait = Path(settings.BASE_DIR) / "static" / "img" / "guru-helmet.jpg"
                if not portrait.is_file():
                    raise CommandError("Guru's helmet portrait is missing.")
                concierge.runway_request("PATCH", "/avatars/" + settings.RUNWAY_AVATAR_ID, {
                    "referenceImage": "data:image/jpeg;base64," + base64.b64encode(portrait.read_bytes()).decode(),
                    "imageProcessing": "none",
                }, timeout=60)
                self.stdout.write("Guru's helmet portrait submitted for processing.")
        except concierge.RunwayError:
            # A provider outage should not take down the website deployment.
            self.stderr.write("Guru persona sync unavailable. Calls will use the current site instructions as an override.")
            return
        self.stdout.write("Guru persona updated." if changed else "Guru persona is up to date.")
