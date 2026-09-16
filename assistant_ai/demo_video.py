"""Industry demo video personas; credentials stay in the existing Runway gateway."""
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from core.demo_profiles import system_prompt
from . import concierge

MANIFEST = Path(__file__).with_name("demo_avatars.json")


def manifest():
    try:
        return json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return {}


def available_profiles():
    if not settings.VIDEO_CONCIERGE_ENABLED or not settings.RUNWAYML_API_SECRET:
        return set()
    return {slug for slug, item in manifest().items() if item.get("id") and item.get("ready")}


def fingerprint(profile):
    return hashlib.sha256((system_prompt(profile) + profile["greeting"] + profile["character"]).encode()).hexdigest()


def create_session(profile):
    item = manifest().get(profile["slug"], {})
    if profile["slug"] not in available_profiles():
        raise concierge.RunwayError("This industry’s video employee is not connected yet. Try the text chat.")
    payload = {
        "model": "gwm1_avatars", "avatar": {"type": "custom", "avatarId": item["id"]},
        "maxDuration": settings.VIDEO_CONCIERGE_MAX_SECONDS,
        # Industry employees simulate a business. They cannot submit leads or navigate.
        "tools": [],
    }
    prompt = system_prompt(profile)
    key = "demo-avatar:" + item["id"] + fingerprint(profile)
    matched = cache.get(key)
    if matched is None:
        try:
            remote = concierge.runway_request("GET", "/avatars/" + item["id"], timeout=3)
            matched = remote.get("status") == "READY" and remote.get("personality") == prompt and remote.get("startScript") == profile["greeting"]
        except concierge.RunwayError:
            matched = False
        cache.set(key, matched, 300 if matched else 30)
    if not matched:
        payload.update(personality=prompt, startScript=profile["greeting"])
    return concierge.runway_request("POST", "/realtime_sessions", payload)
