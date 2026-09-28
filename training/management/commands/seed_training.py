import json
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from training.models import (
    Course,
    Track,
    Module,
    ModuleVersion,
    Skill,
    Quiz,
    Question,
    RolePlayScenario,
    EmployeeProgress,
    RolePlayAttempt,
    CertificationAttempt,
    ManagerReview,
)
from training.curriculum import CORE, ADVANCED, INDUSTRIES, SKILLS


class Command(BaseCommand):
    help = "Seed owner-policy curriculum and available Core lesson packages. Never publishes official training or writes CRM leads."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo",
            action="store_true",
            help="DEBUG only: isolated SYNTHETIC training examples, never official certification.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["demo"] and not settings.DEBUG:
            raise CommandError(
                "Synthetic demonstration records require DEBUG=True. Use an isolated development database."
            )
        course, _ = Course.objects.get_or_create(
            slug="guru-sales-academy", defaults={"title": "Guru Sales Academy"}
        )
        for slug, title in SKILLS.items():
            Skill.objects.get_or_create(slug=slug, defaults={"title": title})
        tracks = [
            (
                "core-sdr",
                "Core SDR Certification",
                "core",
                CORE,
                "Problem-first conversations, useful discovery, qualified assessments and excellent handoffs. Required for independent SDR readiness.",
            ),
            (
                "advanced-sales",
                "Advanced Sales / Closer",
                "advanced",
                ADVANCED,
                "Next phase. Manager-authorized specialist, scoping, proposal and closing responsibilities.",
            ),
        ]
        for industry in INDUSTRIES:
            titles = [
                f"How {industry} Businesses Operate",
                f"{industry} AI Opportunities",
                f"{industry} Discovery",
                f"{industry} Objections & Boundaries",
                f"{industry} Role-Play Certification",
            ]
            tracks.append(
                (
                    slugify(industry) + "-specialist",
                    industry + " Specialization",
                    "industry",
                    titles,
                    "Next phase. Apply Core SDR skills to industry workflows, verified opportunities and appropriate boundaries.",
                )
            )
        for slug, title, kind, titles, description in tracks:
            track, _ = Track.objects.get_or_create(
                slug=slug,
                defaults={
                    "course": course,
                    "title": title,
                    "kind": kind,
                    "description": description,
                },
            )
            for index, title in enumerate(titles, 1):
                module, _ = Module.objects.get_or_create(
                    slug=f"{slug}-{index:02d}",
                    defaults={"track": track, "title": title, "position": index},
                )
                ModuleVersion.objects.get_or_create(
                    module=module,
                    number=1,
                    defaults={
                        "summary": "TRAINING CONTENT IN PRODUCTION. This lesson is not yet published."
                    },
                )
        from training.content_loader import read_package, seed_package

        ready = 0
        for number in range(1, len(CORE) + 1):
            package = read_package(number)
            if package is not None:
                seeded = seed_package(number, package)
                ready += 1
                if number == 1:
                    data, version = package, seeded
        if options["demo"]:
            User = get_user_model()
            employee, created = User.objects.get_or_create(
                username="academy-synthetic-learner",
                defaults={
                    "role": "employee",
                    "first_name": "SYNTHETIC",
                    "last_name": "Learner",
                },
            )
            if created:
                employee.set_unusable_password()
                employee.save()
            manager, created = User.objects.get_or_create(
                username="academy-synthetic-manager",
                defaults={
                    "role": "admin",
                    "first_name": "SYNTHETIC",
                    "last_name": "Manager",
                },
            )
            if created:
                manager.set_unusable_password()
                manager.save()
            track, _ = Track.objects.get_or_create(
                slug="synthetic-training-preview",
                defaults={
                    "course": course,
                    "title": "SYNTHETIC development preview",
                    "kind": "core",
                    "description": "Development records only. Not official employee training.",
                },
            )
            demo, _ = Module.objects.get_or_create(
                slug="synthetic-module-01",
                defaults={
                    "track": track,
                    "title": "SYNTHETIC Module 1 preview",
                    "position": 1,
                },
            )
            dv, new = ModuleVersion.objects.get_or_create(
                module=demo,
                number=1,
                defaults={
                    "summary": "SYNTHETIC development preview only.",
                    "transcript": version.transcript,
                    "scenes": version.scenes,
                    "job_aid": version.job_aid,
                },
            )
            if new:
                quiz = Quiz.objects.create(version=dv)
                for index, q in enumerate(data["questions"][:3], 1):
                    Question.objects.create(
                        quiz=quiz,
                        position=index,
                        **{k: v for k, v in q.items() if k != "skill"},
                    )
                scenario = RolePlayScenario.objects.create(
                    version=dv, **data["scenario"]
                )
                enrollment = CertificationAttempt.objects.create(
                    employee=employee, track=track, assigned_by=manager
                )
                EmployeeProgress.objects.create(
                    employee=employee,
                    version=dv,
                    watched_ranges=[[0, 90]],
                    position_seconds=90,
                    active_seconds=90,
                )
                RolePlayAttempt.objects.create(
                    employee=employee,
                    scenario=scenario,
                    state="review",
                    transcript=[
                        {
                            "role": "assistant",
                            "content": "SYNTHETIC prospect: We lose track of quotes.",
                        },
                        {"role": "user", "content": "How do you follow up now?"},
                    ],
                    handoff="SYNTHETIC FACT: quote follow-up needs exploration. No booking made.",
                )
                ManagerReview.objects.create(
                    enrollment=enrollment,
                    manager=manager,
                    kind="practical",
                    note="SYNTHETIC demonstration of a pending practical review. Not a real assessment.",
                )
            self.stdout.write(
                "SYNTHETIC records created in a separate draft preview track. No certification awarded."
            )
        self.stdout.write(
            f"Curriculum seeded; {ready} complete lesson packages available for owner review. No content published, no CRM leads created."
        )
