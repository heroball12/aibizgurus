from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from assistant_ai.models import Conversation, Message
from assistant_ai.services import choose_openai_key
from audit.models import ActivityLog
from audit.utils import log_activity
from clients.models import AIInstance, BusinessProfile, ClientAccount, Integration
from core.models import IndustryTemplate
from crm.models import Lead


User = get_user_model()


class PlatformFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.template, _ = IndustryTemplate.objects.update_or_create(
            slug="hvac",
            defaults={
                "name": "HVAC",
                "category": "Home Services",
                "default_greeting": "Hi from the HVAC assistant.",
                "system_prompt": "Help HVAC customers and capture qualified leads.",
            },
        )
        cls.user = User.objects.create_user(
            username="client-one",
            email="client@example.com",
            password="TestPass123!",
            role="client",
        )
        cls.account = ClientAccount.objects.create(
            user=cls.user,
            business_name="Northwind HVAC",
            industry_template=cls.template,
            industry=cls.template.name,
            contact_email=cls.user.email,
        )
        BusinessProfile.objects.create(client=cls.account)
        cls.assistant = AIInstance.objects.create_from_template(cls.account, cls.template)

    def test_landing_and_industry_pages_load_real_styles_and_data(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Build Your")
        self.assertContains(response, "AI Workforce")
        self.assertContains(response, '/static/css/landing.css?v=15')
        self.assertContains(response, "img/ai-business-gurus-logo-nav.png")
        self.assertContains(response, 'class="landing-page light-mode"')

        response = self.client.get(reverse("industries"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HVAC")
        self.assertEqual(response.context["industry_source"], "database")

    def test_growth_platform_public_pages_load(self):
        for name in ["solutions", "ai_employees", "pricing", "case_studies", "growth_assessment", "demo"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

        assessment = self.client.get(reverse("growth_assessment"))
        self.assertContains(assessment, "https://calendly.com/theaibizguru/15-minute-intro-to-ai")
        self.assertContains(assessment, "calendly-inline-widget")

        response = self.client.get(reverse("solution_detail", args=["ai-chatbots"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Industry-specific website assistants")

    @override_settings(PUBLIC_BASE_URL="https://aibiz.guru")
    def test_operational_public_endpoints_load(self):
        health = self.client.get(reverse("healthz"))
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        robots = self.client.get(reverse("robots_txt"))
        self.assertEqual(robots.status_code, 200)
        self.assertContains(robots, "Sitemap: https://aibiz.guru/sitemap.xml")

        sitemap = self.client.get(reverse("sitemap_xml"))
        self.assertEqual(sitemap.status_code, 200)
        self.assertContains(sitemap, "<loc>https://aibiz.guru/</loc>")

    def test_signup_creates_database_backed_demo_atomically(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new-client",
                "email": "new-client@example.com",
                "business_name": "New HVAC Co",
                "industry_slug": self.template.slug,
                "password1": "StrongDemoPass123!",
                "password2": "StrongDemoPass123!",
            },
        )
        self.assertRedirects(response, reverse("portal_home"))
        user = User.objects.get(username="new-client")
        account = user.client_accounts.get()
        assistant = account.ai_instances.get()
        self.assertEqual(user.role, "client")
        self.assertEqual(account.activation_status, "demo")
        self.assertEqual(account.industry_template, self.template)
        self.assertEqual(assistant.industry_template, self.template)
        self.assertEqual(assistant.greeting, self.template.default_greeting)
        self.assertEqual(assistant.status, "draft")

    @override_settings(PLATFORM_OPENAI_API_KEY="")
    def test_private_demo_preview_chats_with_fallback_and_captures_lead(self):
        widget_url = reverse("widget", kwargs={"slug": self.assistant.slug})
        api_url = reverse("widget_chat_api", kwargs={"slug": self.assistant.slug})
        self.assertEqual(self.client.get(widget_url).status_code, 404)

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(widget_url).status_code, 200)
        response = self.client.post(
            api_url,
            {"message": "Can I get a quote?", "name": "Pat", "phone": "555-0100"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pricing", response.json()["reply"])
        conversation = Conversation.objects.get(ai_instance=self.assistant)
        self.assertEqual(conversation.messages.count(), 2)
        lead = Lead.objects.get(ai_instance=self.assistant)
        self.assertEqual(lead.lead_type, "client_customer")
        self.assertEqual(lead.client, self.account)

    def test_manual_activation_enables_public_widget_and_paid_routes(self):
        self.account.activation_status = "active"
        self.account.save()
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.status, "active")
        self.assertEqual(self.client.get(reverse("widget", kwargs={"slug": self.assistant.slug})).status_code, 200)

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("client_leads")).status_code, 200)
        self.assertEqual(self.client.get(reverse("client_conversations")).status_code, 200)

    def test_demo_paid_routes_stay_visible_but_redirect_to_activation(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse("client_leads")), reverse("billing_home"))
        response = self.client.get(reverse("client_conversations"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demo conversations are visible")
        dashboard = self.client.get(reverse("portal_home"))
        self.assertContains(dashboard, "🔒")
        self.assertContains(dashboard, "Activate Full Version")

    def test_client_and_ops_can_open_conversation_transcripts(self):
        conversation = Conversation.objects.create(
            ai_instance=self.assistant,
            visitor_id="visitor-123",
            customer_name="Pat Customer",
            customer_phone="555-0100",
            customer_email="pat@example.com",
        )
        Message.objects.create(conversation=conversation, sender="visitor", content="I need a quote.")
        Message.objects.create(conversation=conversation, sender="assistant", content="I can help collect the details.")

        self.client.force_login(self.user)
        list_response = self.client.get(reverse("client_conversations"))
        self.assertContains(list_response, reverse("client_conversation_detail", args=[conversation.pk]))

        detail_response = self.client.get(reverse("client_conversation_detail", args=[conversation.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "I need a quote.")
        self.assertContains(detail_response, "I can help collect the details.")

        other_user = User.objects.create_user(username="other-client", password="OtherPass123!", role="client")
        other_client = ClientAccount.objects.create(user=other_user, business_name="Other Co")
        other_assistant = AIInstance.objects.create(client=other_client, name="Other Assistant")
        other_conversation = Conversation.objects.create(ai_instance=other_assistant, visitor_id="other")
        self.assertEqual(self.client.get(reverse("client_conversation_detail", args=[other_conversation.pk])).status_code, 404)

        employee = User.objects.create_user(username="ops-transcripts", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        ops_response = self.client.get(reverse("ops_conversation_detail", args=[self.account.pk, conversation.pk]))
        self.assertEqual(ops_response.status_code, 200)
        self.assertContains(ops_response, "Conversation Transcript")
        self.assertContains(ops_response, "Pat Customer")

    def test_widget_color_picker_persists_and_renders(self):
        self.client.force_login(self.user)
        settings_url = reverse("assistant_settings", args=[self.assistant.pk])
        response = self.client.get(settings_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="color"')

        response = self.client.post(
            settings_url,
            {
                "name": self.assistant.name,
                "greeting": self.assistant.greeting,
                "system_prompt": self.assistant.system_prompt,
                "tone": self.assistant.tone,
                "model": self.assistant.model,
                "openai_api_mode": self.assistant.openai_api_mode,
                "widget_primary_color": "#ff00aa",
                "collect_name": "on",
                "collect_phone": "on",
            },
        )
        self.assertRedirects(response, settings_url)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.widget_primary_color, "#ff00aa")

        widget = self.client.get(reverse("widget", kwargs={"slug": self.assistant.slug}))
        self.assertContains(widget, "--brand:#ff00aa")

    @override_settings(X_FRAME_OPTIONS="DENY")
    def test_widget_embed_view_is_iframe_exempt(self):
        self.account.activation_status = "active"
        self.account.save()
        response = self.client.get(reverse("widget", kwargs={"slug": self.assistant.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Frame-Options", response.headers)

    def test_role_aware_login_redirects(self):
        for role, expected in [
            ("client", "/portal/"),
            ("employee", "/ops/"),
            ("admin", "/ops/"),
            ("owner", "/owner/"),
        ]:
            user = User.objects.create_user(username=f"login-{role}", password="RolePass123!", role=role)
            response = self.client.post(reverse("login"), {"username": user.username, "password": "RolePass123!"})
            self.assertRedirects(response, expected, fetch_redirect_response=False)
            self.client.logout()

    def test_internal_crm_excludes_client_customer_leads(self):
        internal = Lead.objects.create(lead_type="internal_sales", name="Platform prospect")
        customer = Lead.objects.create(
            lead_type="client_customer", client=self.account, ai_instance=self.assistant, name="Client customer"
        )
        employee = User.objects.create_user(username="ops", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        response = self.client.get(reverse("crm_home"))
        self.assertContains(response, internal.name)
        self.assertNotContains(response, customer.name)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[customer.pk])).status_code, 404)

    def test_employee_can_bulk_upload_internal_sales_leads_csv(self):
        employee = User.objects.create_user(username="csv-ops", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        response = self.client.get(reverse("lead_upload"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload leads from CSV")
        self.assertContains(self.client.get(reverse("crm_home")), reverse("lead_upload"))

        upload = SimpleUploadedFile(
            "leads.csv",
            (
                "name,business_name,industry,phone,email,source,status,notes,value,follow_up_date,assigned_to\n"
                "Ada Buyer,Ada Co,Home Services,555-1111,ada@example.com,CSV List,new,Interested in AI receptionist,2500.00,2026-08-01,csv-ops\n"
                "Ben Founder,Ben Studio,Med Spa,555-2222,ben@example.com,CSV List,follow_up,Needs follow up,1200.50,,\n"
            ).encode(),
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        self.assertRedirects(response, reverse("crm_home"))

        ada = Lead.objects.get(name="Ada Buyer")
        ben = Lead.objects.get(name="Ben Founder")
        self.assertEqual(ada.lead_type, "internal_sales")
        self.assertIsNone(ada.client)
        self.assertIsNone(ada.ai_instance)
        self.assertEqual(ada.assigned_to, employee)
        self.assertEqual(ben.status, "follow_up")
        self.assertEqual(Lead.objects.filter(lead_type="client_customer", name__in=["Ada Buyer", "Ben Founder"]).count(), 0)

    def test_csv_upload_validation_is_all_or_nothing(self):
        employee = User.objects.create_user(username="csv-ops-invalid", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        before = Lead.objects.count()
        upload = SimpleUploadedFile(
            "bad.csv",
            b"name,business_name,email\nBroken Lead,Broken Co,not-an-email\n",
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import stopped. No leads were created.")
        self.assertContains(response, "not-an-email")
        self.assertEqual(Lead.objects.count(), before)

    def test_owner_role_and_admin_changelists_work(self):
        owner = User.objects.create_superuser(
            username="founder", email="founder@example.com", password="OwnerPass123!", role="owner"
        )
        self.client.force_login(owner)
        self.assertEqual(self.client.get(reverse("owner_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("owner_activity_logs")).status_code, 200)
        for url in [
            "/admin/accounts/user/",
            "/admin/clients/clientaccount/",
            "/admin/clients/aiinstance/",
            "/admin/core/industrytemplate/",
            "/admin/crm/lead/",
            "/admin/audit/activitylog/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    @override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
    def test_stripe_webhook_rejects_invalid_signature_when_configured(self):
        response = self.client.post(
            reverse("stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="bad-signature",
        )
        self.assertEqual(response.status_code, 400)

    def test_audit_logging_is_best_effort(self):
        with patch("audit.utils.activity_table_exists", return_value=False):
            self.assertIsNone(log_activity(user=self.user, action="update", message="safe"))
        self.assertTrue(ActivityLog.objects.filter(message__icontains="safe").count() == 0)

    @override_settings(PLATFORM_OPENAI_API_KEY="platform-test-key", OPENAI_API_KEY="legacy-key")
    def test_platform_key_setting_and_encrypted_client_override(self):
        self.assertEqual(choose_openai_key(self.assistant), "platform-test-key")
        integration = Integration.objects.create(client=self.account, integration_type="openai", is_active=True)
        integration.set_credential("api_key", "client-test-key")
        integration.save()
        self.assistant.openai_api_mode = "client"
        self.assistant.save()
        self.assertEqual(choose_openai_key(self.assistant), "client-test-key")
        self.assertNotIn("client-test-key", str(integration.credentials))

    def test_current_openai_client_constructs_on_python_314(self):
        from openai import OpenAI

        self.assertEqual(type(OpenAI(api_key="test-key")).__name__, "OpenAI")

    @override_settings(PLATFORM_OPENAI_API_KEY="platform-test-key", OPENAI_MODEL="gpt-4o-mini")
    @patch("assistant_ai.services.OpenAI")
    def test_configured_openai_response_path(self, openai_client):
        conversation = Conversation.objects.create(ai_instance=self.assistant, visitor_id="openai-test")
        Message.objects.create(conversation=conversation, sender="visitor", content="What services do you offer?")
        openai_client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="We can help with HVAC service."))]
        )

        from assistant_ai.services import generate_ai_reply

        reply = generate_ai_reply(self.assistant, conversation, "What services do you offer?")
        self.assertEqual(reply, "We can help with HVAC service.")
        openai_client.assert_called_once_with(api_key="platform-test-key")
        call = openai_client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "gpt-4o-mini")
        self.assertEqual(call["messages"][-1]["content"], "What services do you offer?")
