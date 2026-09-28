import tempfile
from pathlib import Path
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.middleware.gzip import GZipMiddleware
from django.test import SimpleTestCase, RequestFactory, override_settings
from training.media import local_path, local_response


class PrivateDiskMediaTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "core/02/video.mp4"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"0123456789")
        self.asset = SimpleNamespace(storage_key="core/02/video.mp4", kind="video")
        self.override = override_settings(
            TRAINING_S3_BUCKET="", TRAINING_MEDIA_ROOT=str(self.root)
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.factory = RequestFactory()

    def test_full_response_and_single_byte_ranges(self):
        for header, status, expected, content_range in [
            ("", 200, b"0123456789", None),
            ("bytes=2-5", 206, b"2345", "bytes 2-5/10"),
            ("bytes=7-", 206, b"789", "bytes 7-9/10"),
            ("bytes=-3", 206, b"789", "bytes 7-9/10"),
            ("bytes=8-999", 206, b"89", "bytes 8-9/10"),
        ]:
            with self.subTest(header=header):
                response = local_response(
                    self.factory.get("/", HTTP_RANGE=header), self.asset
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(b"".join(response.streaming_content), expected)
                self.assertEqual(response["Content-Length"], str(len(expected)))
                self.assertEqual(response.get("Content-Range"), content_range)
                self.assertIn("private", response["Cache-Control"])
                response.close()

    def test_head_has_headers_without_open_stream(self):
        response = local_response(
            self.factory.head("/", HTTP_RANGE="bytes=1-3"), self.asset
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Length"], "3")
        self.assertEqual(response.content, b"")

    def test_global_compression_preserves_video_bytes_and_range_lengths(self):
        for header in ("", "bytes=2-5"):
            with self.subTest(header=header):
                request = self.factory.get(
                    "/", HTTP_RANGE=header, HTTP_ACCEPT_ENCODING="gzip, deflate"
                )
                response = GZipMiddleware(
                    lambda request: local_response(request, self.asset)
                )(request)
                expected = b"2345" if header else b"0123456789"
                self.assertEqual(response["Content-Encoding"], "identity")
                self.assertEqual(response["Content-Length"], str(len(expected)))
                self.assertEqual(b"".join(response.streaming_content), expected)
                self.assertEqual(
                    response.get("Content-Range"), "bytes 2-5/10" if header else None
                )
                response.close()

    def test_invalid_or_multiple_ranges_are_rejected(self):
        for value in [
            "bytes=99-",
            "bytes=5-2",
            "bytes=-0",
            "bytes=-",
            "bytes=1-2,4-5",
            "items=1-2",
        ]:
            response = local_response(
                self.factory.get("/", HTTP_RANGE=value), self.asset
            )
            self.assertEqual(response.status_code, 416, value)
            self.assertEqual(response["Content-Range"], "bytes */10")

    def test_unknown_if_range_validator_returns_full_file(self):
        response = local_response(
            self.factory.get("/", HTTP_RANGE="bytes=1-2", HTTP_IF_RANGE="unknown"),
            self.asset,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"0123456789")
        response.close()

    def test_traversal_and_symlink_escape_are_rejected(self):
        for key in ["../secret", "/etc/passwd", "core/../../secret"]:
            with self.assertRaises(ValidationError):
                local_path(SimpleNamespace(storage_key=key))
        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside) / "private.mp4"
            other.write_bytes(b"not public")
            (self.root / "escape.mp4").symlink_to(other)
            with self.assertRaises(ValidationError):
                local_path(SimpleNamespace(storage_key="escape.mp4"))

    def test_caption_mime_type_supports_same_origin_tracks(self):
        self.asset.kind = "captions"
        response = local_response(self.factory.get("/"), self.asset)
        self.assertEqual(response["Content-Type"], "text/vtt; charset=utf-8")
        response.close()
