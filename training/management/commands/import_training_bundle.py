"""Attach verified, locally uploaded media without publishing training."""

import hashlib
import json
import math
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from training.content_loader import read_package
from training.media import validate_key
from training.models import Module, LessonAsset


def checked_file(root, record):
    try:
        relative = validate_key(record["path"])
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Missing file or path outside the bundle.")
        if path.stat().st_size != record["bytes"]:
            raise ValueError("File size does not match.")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise ValueError("SHA-256 does not match.")
        return path
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise CommandError(f"Invalid bundle file: {error}") from error


class Command(BaseCommand):
    help = "Verify a Core Academy folder and attach its private media for owner review. Never publishes."

    def add_arguments(self, parser):
        parser.add_argument("folder", type=Path)
        parser.add_argument(
            "--check",
            action="store_true",
            help="Verify all files without changing records.",
        )

    def handle(self, *args, **options):
        root = options["folder"].expanduser().resolve()
        try:
            manifest = json.loads((root / "manifest.json").read_text())
            if manifest["format"] != "aibg-core-academy-1":
                raise ValueError("Unsupported bundle format.")
            entries = manifest["modules"]
            if len(entries) != 16 or {e["number"] for e in entries} != set(
                range(1, 17)
            ):
                raise ValueError(
                    "A complete Core delivery must contain each of the 16 lessons once."
                )
            checked = []
            for entry in entries:
                number = entry["number"]
                package = read_package(number)
                content = checked_file(root, entry["content"])
                if json.loads(content.read_text()) != package:
                    raise ValueError(
                        f"Module {number} does not match this deployed curriculum. Deploy the matching code first."
                    )
                qa = json.loads(checked_file(root, entry["qa"]).read_text())
                runtime = entry["duration_seconds"]
                if not isinstance(runtime, (int, float)) or not 1 <= runtime <= 3600:
                    raise ValueError("Invalid lesson runtime.")
                if (
                    qa["full_decode"] != "passed"
                    or abs(qa["duration_seconds"] - runtime) > 0.05
                ):
                    raise ValueError(
                        "The delivery QA report does not match the runtime."
                    )
                assets = entry["assets"]
                if set(assets) != {"video", "captions", "poster"}:
                    raise ValueError("Video, captions and poster are required.")
                for record in assets.values():
                    checked_file(root, record)
                if (
                    qa["sha256"] != assets["video"]["sha256"]
                    or qa["source_sha256"] != entry["content"]["sha256"]
                ):
                    raise ValueError(
                        "The delivery QA report does not match the video and source."
                    )
                for record in entry["supporting_files"]:
                    checked_file(root, record)
                chapters = entry["chapters"]
                if len(chapters) != len(package["scenes"]):
                    raise ValueError("Chapter count does not match the lesson.")
                previous = 0
                for chapter, scene in zip(chapters, package["scenes"]):
                    if (
                        chapter["title"] != scene["title"]
                        or not previous
                        <= chapter["start"]
                        < chapter["end"]
                        <= runtime + 0.05
                    ):
                        raise ValueError("Invalid or mismatched chapter timings.")
                    previous = chapter["end"]
                checked.append((entry, package))
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise CommandError(f"Bundle verification failed: {error}") from error
        self.stdout.write(
            f"All 16 lesson packages and file checksums verified at {root}."
        )
        if options["check"]:
            return
        configured = getattr(settings, "TRAINING_MEDIA_ROOT", "")
        if not configured or Path(configured).expanduser().resolve() != root:
            raise CommandError(
                "Set TRAINING_MEDIA_ROOT to this exact uploaded bundle folder before importing. No records changed."
            )
        if getattr(settings, "TRAINING_S3_BUCKET", ""):
            raise CommandError(
                "This import uses private disk playback. Clear TRAINING_S3_BUCKET or use the S3 asset workflow instead."
            )
        with transaction.atomic():
            call_command("seed_training", verbosity=0, stdout=self.stdout)
            plans = []
            for entry, package in checked:
                version = (
                    Module.objects.get(slug=f"core-sdr-{entry['number']:02d}")
                    .versions.order_by("-number")
                    .first()
                )
                scenes = []
                for scene, chapter in zip(package["scenes"], entry["chapters"]):
                    start = chapter["start"]
                    scenes.append(
                        {
                            **scene,
                            "start": start,
                            "end": chapter["end"],
                            "time": f"{int(start)//60:02}:{int(start)%60:02}",
                        }
                    )
                duration = math.ceil(entry["duration_seconds"])
                expected = {
                    kind: item["path"] for kind, item in entry["assets"].items()
                }
                existing = {a.kind: a.storage_key for a in version.assets.all()}
                if version.status in {"approved", "published", "retired"}:
                    if (
                        version.scenes != scenes
                        or version.duration_seconds != duration
                        or existing != expected
                    ):
                        raise CommandError(
                            f'Module {entry["number"]} is immutable. Create an explicit draft revision before changing its media.'
                        )
                elif version.transcript != "\n\n".join(
                    s["narration"] for s in package["scenes"]
                ):
                    raise CommandError(
                        f'Module {entry["number"]} has different content. Resolve the revision before importing.'
                    )
                else:
                    plans.append((version, scenes, duration, expected))
            for version, scenes, duration, expected in plans:
                version.scenes, version.duration_seconds = scenes, duration
                version.save(update_fields=["scenes", "duration_seconds"])
                for kind, key in expected.items():
                    asset = version.assets.filter(kind=kind).first()
                    if asset and asset.storage_key == key:
                        continue
                    LessonAsset.objects.update_or_create(
                        version=version,
                        kind=kind,
                        defaults={"storage_key": key, "reviewed": False},
                    )
        self.stdout.write(
            self.style.SUCCESS(
                "Private videos attached with actual chapter timings. Review and publication remain owner actions; no employee credit was awarded."
            )
        )
