"""Provision public sample employees once; never creates paid live sessions."""
import base64
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant_ai import concierge, demo_video
from core.demo_profiles import CHARACTERS, profiles, system_prompt


class Command(BaseCommand):
    help = "Create/update Runway industry demo characters and save their public IDs. No live calls are started."

    def add_arguments(self, parser):
        parser.add_argument("--industry", action="append", help="Limit to a catalog slug; repeat for multiple industries.")
        parser.add_argument("--poll-only", action="store_true", help="Only refresh readiness of existing characters.")
        parser.add_argument("--retry-failed", action="store_true", help="Resubmit failed characters after correcting their configuration.")

    def handle(self, *args, **options):
        if not settings.RUNWAYML_API_SECRET:
            raise CommandError("RUNWAYML_API_SECRET is not configured.")
        entries = demo_video.manifest()
        selected = [p for p in profiles() if not options["industry"] or p["slug"] in options["industry"]]
        if not selected:
            raise CommandError("No matching demo industries.")
        for profile in selected:
            slug = profile["slug"]
            entry = entries.get(slug, {})
            try:
                if not entry.get("id"):
                    if options["poll_only"]:
                        continue
                    image = Path(settings.BASE_DIR) / "static" / "img" / "demo-characters" / (profile["character"] + ".jpg")
                    if not image.exists():
                        self.stdout.write(f"{slug}: portrait not ready; skipped")
                        continue
                    character = CHARACTERS[profile["character"]]
                    result = concierge.runway_request("POST", "/avatars", {
                        "name": f"AIBG Demo • {profile['industry']} • {profile['name']}",
                        "referenceImage": "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode(),
                        "voice": {"type": "runway-live-preset", "presetId": character["voice"]},
                        "personality": system_prompt(profile), "startScript": profile["greeting"], "imageProcessing": "none",
                    }, timeout=60)
                    entry = {"id": str(uuid.UUID(result["id"])), "fingerprint": demo_video.fingerprint(profile), "ready": False}
                    entries[slug] = entry
                    self.save(entries)
                remote = concierge.runway_request("GET", "/avatars/" + entry["id"])
                name = f"AIBG Demo • {profile['industry']} • {profile['name']}"
                if not options["poll_only"] and (remote.get("name") != name or remote.get("personality") != system_prompt(profile) or remote.get("startScript") != profile["greeting"]):
                    concierge.runway_request("PATCH", "/avatars/" + entry["id"], {"name": name, "personality": system_prompt(profile), "startScript": profile["greeting"]})
                if options["retry_failed"] and not options["poll_only"] and remote.get("status") == "FAILED":
                    image = Path(settings.BASE_DIR) / "static" / "img" / "demo-characters" / (profile["character"] + ".jpg")
                    concierge.runway_request("PATCH", "/avatars/" + entry["id"], {
                        "referenceImage": "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode(),
                        "imageProcessing": "none", "personality": system_prompt(profile), "startScript": profile["greeting"],
                    }, timeout=60)
                remote = concierge.runway_request("GET", "/avatars/" + entry["id"])
                entry["fingerprint"] = demo_video.fingerprint(profile)
                entry["ready"] = remote.get("status") == "READY"
                entries[slug] = entry
                self.save(entries)
                self.stdout.write(f"{slug}: {remote.get('status', 'PROCESSING')}")
            except (concierge.RunwayError, KeyError, ValueError) as exc:
                self.save(entries)
                raise CommandError(f"{slug}: provider setup did not complete. Saved completed progress; rerun to resume.") from None
        self.stdout.write(f"{sum(bool(e.get('ready')) for e in entries.values())} video employees ready.")

    @staticmethod
    def save(entries):
        temporary = demo_video.MANIFEST.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
        temporary.replace(demo_video.MANIFEST)
