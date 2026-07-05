from dataclasses import dataclass
from django.utils.text import slugify
from .models import IndustryTemplate
from .industry_loader import load_industries

@dataclass
class IndustryOption:
    name: str
    slug: str
    category: str
    summary: str = ""
    default_greeting: str = ""
    system_prompt: str = ""
    lead_fields: list = None
    common_questions: list = None
    escalation_rules: str = ""

def option_from_dict(item):
    return IndustryOption(
        name=item.get("name", "Generic Local Service"),
        slug=item.get("slug") or slugify(item.get("name", "Generic Local Service")),
        category=item.get("category", "General"),
        summary=item.get("summary", ""),
        default_greeting=item.get("default_greeting", ""),
        system_prompt=item.get("system_prompt", ""),
        lead_fields=item.get("lead_fields", []),
        common_questions=item.get("common_questions", []),
        escalation_rules=item.get("escalation_rules", ""),
    )

def get_industry_options():
    db_items = list(IndustryTemplate.objects.all().order_by("category", "name"))
    if db_items:
        return db_items, "database"

    # Fallback for local/dev cases where seed command prints correctly but the web
    # process is pointed at a different/empty sqlite DB.
    raw_items, _source = load_industries()
    data_items = sorted(raw_items, key=lambda x: (x.get("category", ""), x.get("name", "")))
    return [option_from_dict(item) for item in data_items], "builtin"

def get_option_by_slug(slug):
    if not slug:
        return None, "none"

    obj = IndustryTemplate.objects.filter(slug=slug).first()
    if obj:
        return obj, "database"

    raw_items, _source = load_industries()
    for item in raw_items:
        item_slug = item.get("slug") or slugify(item.get("name", ""))
        if item_slug == slug:
            return option_from_dict(item), "builtin"

    return None, "none"

def ensure_template_for_option(option):
    """
    If signup used a built-in fallback option, create/get a real DB template
    before creating AIInstance from template.
    """
    if option is None:
        return IndustryTemplate.objects.filter(slug="generic-local-service").first()

    if isinstance(option, IndustryTemplate):
        return option

    defaults = {
        "slug": option.slug,
        "category": option.category,
        "summary": option.summary,
        "default_greeting": option.default_greeting,
        "system_prompt": option.system_prompt,
        "lead_fields": option.lead_fields or [],
        "common_questions": option.common_questions or [],
        "escalation_rules": option.escalation_rules,
        "is_supported": True,
    }
    obj, _ = IndustryTemplate.objects.update_or_create(name=option.name, defaults=defaults)
    return obj
