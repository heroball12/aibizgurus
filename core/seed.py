from django.db import OperationalError, ProgrammingError
from django.utils.text import slugify
from .models import IndustryTemplate
from .industry_loader import load_industries

def seed_industries(stdout=None, force=False):
    """
    Seed supported industry templates.

    Safe to run repeatedly. Returns (created_count, updated_count, total_count).
    """
    industries, source = load_industries()
    if stdout:
        stdout.write(f"Industry source: {source}")
        stdout.write(f"Industry source count: {len(industries)}")

    if not industries:
        raise RuntimeError("Industry source is empty. Cannot seed industries.")

    created_count = 0
    updated_count = 0

    for item in industries:
        data = dict(item)
        name = data.get("name")
        if not name:
            continue
        data.setdefault("slug", slugify(name))
        data.setdefault("is_supported", True)
        data.setdefault("category", "General")
        data.setdefault("summary", f"AI receptionist template for {name}.")
        data.setdefault("default_greeting", f"Hi! I’m the AI assistant for this {name} business. How can I help today?")
        data.setdefault("system_prompt", f"You are an AI receptionist for a {name} business. Answer questions using business info and capture qualified leads.")
        data.setdefault("lead_fields", ["name", "phone", "email", "need/request"])
        data.setdefault("common_questions", [])
        data.setdefault("escalation_rules", "")

        obj, created = IndustryTemplate.objects.update_or_create(
            name=name,
            defaults=data,
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    total_count = IndustryTemplate.objects.count()
    if stdout:
        stdout.write(f"Industries created: {created_count}")
        stdout.write(f"Industries updated: {updated_count}")
        stdout.write(f"Industries total: {total_count}")
    return created_count, updated_count, total_count

def safe_seed_industries(stdout=None):
    try:
        return seed_industries(stdout=stdout)
    except (OperationalError, ProgrammingError):
        return (0, 0, 0)
