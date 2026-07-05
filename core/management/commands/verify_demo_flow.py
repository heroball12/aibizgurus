from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import Client
from django.conf import settings

from core.models import IndustryTemplate
from core.seed import seed_industries
from core.industry_loader import load_industries
from clients.models import ClientAccount, BusinessProfile, AIInstance

User = get_user_model()

class Command(BaseCommand):
    help = "Verify database-backed industry signup/demo/widget flow"

    def add_arguments(self, parser):
        parser.add_argument("--create-test", action="store_true", help="Create a test client/assistant if verification passes.")
        parser.add_argument("--username", default="demo_test_client", help="Username for --create-test.")

    def handle(self, *args, **kwargs):
        self.stdout.write("Checking industry templates...")
        source_items, source_name = load_industries()
        self.stdout.write(f"Industry loader source: {source_name}")
        self.stdout.write(f"Industry loader count: {len(source_items)}")
        if IndustryTemplate.objects.count() == 0:
            self.stdout.write("No industries found. Seeding now...")
            seed_industries(stdout=self.stdout)

        count = IndustryTemplate.objects.count()
        generic = IndustryTemplate.objects.filter(slug="generic-local-service").first()
        hvac = IndustryTemplate.objects.filter(slug="hvac").first()
        cannabis = IndustryTemplate.objects.filter(name__icontains="Cannabis").first()

        self.stdout.write(f"Industries loaded: {count}")
        self.stdout.write(f"Generic Local Service exists: {'yes' if generic else 'no'}")
        self.stdout.write(f"HVAC exists: {'yes' if hvac else 'no'}")
        self.stdout.write(f"Cannabis template exists: {'yes' if cannabis else 'no'}")

        if count == 0:
            self.stderr.write(self.style.ERROR("FAIL: No industries are available."))
            return

        # Verify signup page can see DB-backed industries.
        client = Client(HTTP_HOST="127.0.0.1")
        response = client.get(reverse("signup"))
        self.stdout.write(f"Signup page status: {response.status_code}")
        content = response.content.decode("utf-8", errors="ignore")
        has_hvac = "HVAC" in content
        has_count = f"{count} industry templates loaded" in content
        self.stdout.write(f"Signup page shows HVAC: {'yes' if has_hvac else 'no'}")
        self.stdout.write(f"Signup page shows DB count: {'yes' if has_count else 'no'}")

        template = hvac or generic or IndustryTemplate.objects.first()

        if kwargs["create_test"]:
            username = kwargs["username"]
            user, _ = User.objects.get_or_create(username=username, defaults={"email": "demo-test@example.com", "role": "client"})
            user.role = "client"
            user.set_password("DemoTest123!")
            user.save()

            client_account, _ = ClientAccount.objects.get_or_create(
                user=user,
                defaults={
                    "business_name": "Demo Flow Test Business",
                    "industry": template.name,
                    "contact_email": user.email,
                    "status": "onboarding",
                }
            )
            if client_account.industry_template_id != template.pk or client_account.industry != template.name:
                client_account.industry_template = template
                client_account.industry = template.name
                client_account.save(update_fields=["industry_template", "industry"])
            BusinessProfile.objects.get_or_create(client=client_account)
            assistant = client_account.ai_instances.first()
            if not assistant:
                assistant = AIInstance.objects.create_from_template(client_account, template)
            elif assistant.industry_template_id != template.pk:
                assistant.industry_template = template
                assistant.industry = template.name
                assistant.save(update_fields=["industry_template", "industry"])

            self.stdout.write(f"Demo client: {client_account.business_name}")
            self.stdout.write(f"Demo assistant: {assistant.name}")
            self.stdout.write(f"Demo assistant industry: {assistant.industry}")
            self.stdout.write(f"Widget URL: /ai/widget/{assistant.slug}/")

        if count > 0 and response.status_code == 200 and has_hvac:
            self.stdout.write(self.style.SUCCESS("PASS: database-backed industry signup/demo flow is connected."))
        else:
            self.stderr.write(self.style.WARNING("WARNING: Database has industries, but signup HTML did not show expected options. Check template/context."))
