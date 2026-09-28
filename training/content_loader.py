"""Version-preserving imports of complete, reviewed-source lesson packages."""

import json
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from .curriculum import CORE, SKILLS
from .models import Module, ModuleVersion, Quiz, Question, RolePlayScenario, Skill


def read_package(number):
    path = Path(settings.BASE_DIR) / f"training/content/module{number}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if not 1 <= number <= len(CORE) or data["title"] != CORE[number - 1]:
        raise ValidationError("The package must match its curriculum module.")
    if not data.get("scenes") or not data.get("job_aid") or not data.get("scenario"):
        raise ValidationError("Provide narration, field guide and practical scenario.")
    if len(data.get("questions", [])) < 8:
        raise ValidationError(
            "A complete Core lesson needs at least eight scenario questions."
        )
    if not set(data["skills"]) <= set(SKILLS):
        raise ValidationError("The lesson references an unknown skill.")
    for q in data["questions"]:
        if q["skill"] not in SKILLS:
            raise ValidationError("The quiz references an unknown skill.")
        if not (
            isinstance(q["choices"], list)
            and len(q["choices"]) >= 2
            and type(q["correct_index"]) is int
            and 0 <= q["correct_index"] < len(q["choices"])
        ):
            raise ValidationError("The quiz has an invalid answer key.")
        if not q["explanation"].strip():
            raise ValidationError("Every question needs explanatory feedback.")
    return data


def seed_package(number, data):
    module = Module.objects.get(slug=f"core-sdr-{number:02d}")
    version = module.versions.order_by("-number").first()
    transcript = "\n\n".join(s["narration"] for s in data["scenes"])
    if version.transcript and version.policy_version != data["policy_version"]:
        version = ModuleVersion.objects.create(
            module=module,
            number=version.number + 1,
            policy_version=data["policy_version"],
        )
    if version.status == "draft" and not version.transcript:
        version.policy_version = data["policy_version"]
        version.duration_seconds = data["duration_seconds"]
        version.summary = data["summary"]
        version.transcript = transcript
        version.scenes = data["scenes"]
        version.job_aid = data["job_aid"]
        version.save()
        module.skills.set(Skill.objects.filter(slug__in=data["skills"]))
        quiz = Quiz.objects.create(version=version)
        for index, q in enumerate(data["questions"], 1):
            question = Question(
                quiz=quiz,
                position=index,
                skill=Skill.objects.get(slug=q["skill"]),
                **{k: v for k, v in q.items() if k != "skill"},
            )
            question.full_clean()
            question.save()
        RolePlayScenario.objects.create(version=version, **data["scenario"])
        version.status = "owner_review"
        version._transition = True
        version.save()
    return version
