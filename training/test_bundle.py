import hashlib
import io
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from . import services
from .models import LessonAsset, Module, ModuleVersion, RolePlayScenario


@override_settings(TRAINING_S3_BUCKET="")
class TrainingBundleTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.setting = override_settings(TRAINING_MEDIA_ROOT=str(self.root))
        self.setting.enable()
        self.addCleanup(self.setting.disable)
        self.manifest = {"format": "aibg-core-academy-1", "modules": []}
        for n in range(1, 17):
            source = Path(settings.BASE_DIR) / f"training/content/module{n}.json"
            package = json.loads(source.read_text())
            content = self.write(f"{n:02d}/lesson.json", source.read_bytes())
            video = self.write(f"{n:02d}/video.mp4", b"SYNTHETIC TEST FIXTURE")
            captions = self.write(f"{n:02d}/captions.vtt", b"WEBVTT\n")
            poster = self.write(f"{n:02d}/poster.jpg", b"SYNTHETIC TEST FIXTURE")
            duration = len(package["scenes"]) * 60 + 0.5
            qa = self.write(
                f"{n:02d}/qa.json",
                json.dumps(
                    {
                        "full_decode": "passed",
                        "duration_seconds": duration,
                        "sha256": video["sha256"],
                        "source_sha256": content["sha256"],
                    }
                ).encode(),
            )
            chapters = [
                {"title": scene["title"], "start": i * 60, "end": (i + 1) * 60}
                for i, scene in enumerate(package["scenes"])
            ]
            self.manifest["modules"].append(
                {
                    "number": n,
                    "content": content,
                    "qa": qa,
                    "assets": {"video": video, "captions": captions, "poster": poster},
                    "duration_seconds": duration,
                    "chapters": chapters,
                    "supporting_files": [],
                }
            )
        self.save_manifest()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return {
            "path": name,
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }

    def save_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def run_import(self, *extra):
        call_command(
            "import_training_bundle", str(self.root), *extra, stdout=io.StringIO()
        )

    def test_check_validates_without_creating_records(self):
        self.run_import("--check")
        self.assertEqual(Module.objects.count(), 0)

    def test_import_is_idempotent_and_never_publishes_or_reviews_assets(self):
        self.run_import()
        before = (ModuleVersion.objects.count(), LessonAsset.objects.count())
        self.run_import()
        self.assertEqual(
            (ModuleVersion.objects.count(), LessonAsset.objects.count()), before
        )
        self.assertEqual(LessonAsset.objects.count(), 48)
        self.assertFalse(LessonAsset.objects.filter(reviewed=True).exists())
        self.assertFalse(
            ModuleVersion.objects.filter(status__in=["approved", "published"]).exists()
        )
        version = Module.objects.get(slug="core-sdr-02").versions.latest("number")
        self.assertEqual(version.duration_seconds, 721)
        self.assertEqual(version.runtime_label, "12:01")
        self.assertEqual(version.scenes[1]["start"], 60)
        self.assertEqual(version.scenes[1]["time"], "01:00")
        self.assertTrue(
            RolePlayScenario.objects.get(version__module__slug="core-sdr-16").capstone
        )
        self.assertFalse(
            RolePlayScenario.objects.get(version__module__slug="core-sdr-01").capstone
        )

    def test_corrupt_video_rejects_whole_bundle_before_database_changes(self):
        (self.root / "16/video.mp4").write_bytes(b"CORRUPT")
        with self.assertRaises(CommandError):
            self.run_import()
        self.assertEqual(Module.objects.count(), 0)

    def test_missing_module_rejects_partial_delivery(self):
        self.manifest["modules"].pop()
        self.save_manifest()
        with self.assertRaises(CommandError):
            self.run_import()
        self.assertEqual(Module.objects.count(), 0)

    def test_curriculum_mismatch_rejects_before_import(self):
        entry = self.manifest["modules"][3]
        entry["content"] = self.write(
            "04/lesson.json", b'{"title":"Different content"}'
        )
        self.save_manifest()
        with self.assertRaisesMessage(CommandError, "matching code"):
            self.run_import()
        self.assertEqual(Module.objects.count(), 0)

    def test_escaping_asset_path_is_rejected(self):
        self.manifest["modules"][0]["assets"]["video"]["path"] = "../outside.mp4"
        self.save_manifest()
        with self.assertRaises(CommandError):
            self.run_import()
        self.assertEqual(Module.objects.count(), 0)

    def test_wrong_private_root_leaves_database_unchanged(self):
        with override_settings(TRAINING_MEDIA_ROOT=""):
            with self.assertRaisesMessage(CommandError, "TRAINING_MEDIA_ROOT"):
                self.run_import()
        self.assertEqual(Module.objects.count(), 0)

    def test_reimport_preserves_review_and_refuses_approved_media_changes(self):
        self.run_import()
        version = Module.objects.get(slug="core-sdr-02").versions.latest("number")
        for asset in version.assets.all():
            asset.reviewed = True
            asset.save()
        owner = get_user_model().objects.create_user(
            username="bundle-owner", role="owner"
        )
        services.transition(owner, version, "approved")
        self.run_import()
        self.assertEqual(version.assets.filter(reviewed=True).count(), 3)
        entry = self.manifest["modules"][1]
        entry["assets"]["video"] = self.write(
            "02/revised.mp4", b"REVISED SYNTHETIC TEST FIXTURE"
        )
        qa = json.loads((self.root / "02/qa.json").read_text())
        qa["sha256"] = entry["assets"]["video"]["sha256"]
        entry["qa"] = self.write("02/qa.json", json.dumps(qa).encode())
        self.save_manifest()
        before = ModuleVersion.objects.count()
        with self.assertRaisesMessage(CommandError, "immutable"):
            self.run_import()
        self.assertEqual(ModuleVersion.objects.count(), before)
        self.assertEqual(version.assets.get(kind="video").storage_key, "02/video.mp4")
