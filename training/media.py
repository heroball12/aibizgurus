"""Authorized access to private S3 or persistent-disk training assets."""

import re
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import FileResponse, HttpResponse, StreamingHttpResponse


def configured():
    return bool(
        getattr(settings, "TRAINING_S3_BUCKET", "")
        or getattr(settings, "TRAINING_MEDIA_ROOT", "")
    )


def local_path(asset):
    """Resolve only a registered asset under the configured private root."""
    value = getattr(settings, "TRAINING_MEDIA_ROOT", "")
    if not value:
        raise ImproperlyConfigured("Private training media is not configured.")
    root = Path(value).expanduser().resolve()
    path = (root / validate_key(asset.storage_key)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValidationError("Training media is unavailable.")
    return path


def local_response(request, asset):
    """Authenticated same-origin playback with byte ranges for seeking.

    Authorization is performed by the asset view before entering this function.
    Nothing under this directory is mounted as a public Django media route.
    """
    path = local_path(asset)
    size = path.stat().st_size
    content_type = {
        "video": "video/mp4",
        "captions": "text/vtt; charset=utf-8",
        "poster": "image/png" if path.suffix.lower() == ".png" else "image/jpeg",
    }[asset.kind]
    start, end, partial = 0, size - 1, False
    value = request.headers.get("Range", "")
    # Without a validator match, If-Range asks for the full representation.
    if value and not request.headers.get("If-Range"):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value) if len(value) < 150 else None
        if match and any(match.groups()) and size:
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                length = int(last)
                start, end = max(0, size - length), size - 1
            partial = 0 <= start <= end < size
        if not partial:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Accept-Ranges"] = "bytes"
            response["Cache-Control"] = "private, no-store"
            return response
    length = max(0, end - start + 1)
    if request.method == "HEAD":
        response = HttpResponse(
            status=206 if partial else 200, content_type=content_type
        )
    elif partial:

        def chunks():
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        response = StreamingHttpResponse(
            chunks(), status=206, content_type=content_type
        )
    else:
        response = FileResponse(path.open("rb"), content_type=content_type)
    response["Content-Length"] = length
    # Global gzip middleware must not transform byte ranges or remove their
    # length: video seeking depends on these being the original file bytes.
    response["Content-Encoding"] = "identity"
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if partial:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


def validate_key(key):
    if (
        not isinstance(key, str)
        or not re.fullmatch(r"[a-zA-Z0-9_/.-]{1,500}", key)
        or ".." in key.split("/")
        or key.startswith("/")
    ):
        raise ValidationError(
            "Use a valid private storage object key, not a temporary URL."
        )
    return key


def media_url(asset):
    if not getattr(settings, "TRAINING_S3_BUCKET", ""):
        raise ImproperlyConfigured("Private training media is not configured.")
    key = validate_key(asset.storage_key)
    import boto3
    from botocore.config import Config

    endpoint = getattr(settings, "TRAINING_S3_ENDPOINT", "") or None
    if endpoint and not endpoint.startswith("https://"):
        raise ImproperlyConfigured("Training storage must use HTTPS.")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=getattr(settings, "TRAINING_S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4"),
    )
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.TRAINING_S3_BUCKET, "Key": key},
        ExpiresIn=300,
    )
