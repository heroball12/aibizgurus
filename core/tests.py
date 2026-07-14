from unittest.mock import patch
from types import SimpleNamespace
import io
import tempfile
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from assistant_ai.models import AssistantRole, Conversation, Message, UsageRecord
from assistant_ai.services import choose_openai_key
from audit.models import ActivityLog, StaffMessage, StaffMessageAttachment, StaffMessageThread, TimeClockEntry
from audit.utils import log_activity
from clients.models import AIInstance, BusinessProfile, ClientAccount, Integration
from core.models import IndustryTemplate
from crm.intelligence import classify_sales_note
from crm.models import Lead, LeadActivity, LeadImport


User = get_user_model()


def build_minimal_xlsx(rows, sheet_name="Tracker"):
    def cell_ref(col_index, row_index):
        letters = ""
        col = col_index + 1
        while col:
            col, remainder = divmod(col - 1, 26)
            letters = chr(65 + remainder) + letters
        return f"{letters}{row_index}"

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row):
            ref = cell_ref(col_index, row_index)
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        zf.writestr("xl/workbook.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>
</workbook>""")
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""")
        zf.writestr("xl/worksheets/sheet1.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{''.join(sheet_rows)}</sheetData></worksheet>""")
    return buffer.getvalue()


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
        employee = User.objects.create_user(username="ops", password="OpsPass123!", role="employee")
        internal = Lead.objects.create(lead_type="internal_sales", name="Platform prospect", assigned_to=employee)
        customer = Lead.objects.create(
            lead_type="client_customer", client=self.account, ai_instance=self.assistant, name="Client customer"
        )
        self.client.force_login(employee)
        response = self.client.get(reverse("crm_home"))
        self.assertContains(response, internal.name)
        self.assertNotContains(response, customer.name)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[customer.pk])).status_code, 404)

    def test_sdr_sales_intelligence_only_shows_assigned_leads(self):
        sdr = User.objects.create_user(username="privacy-sdr", password="OpsPass123!", role="employee")
        other_sdr = User.objects.create_user(username="other-privacy-sdr", password="OpsPass123!", role="employee")
        admin = User.objects.create_user(username="privacy-admin", password="OpsPass123!", role="admin")
        mine = Lead.objects.create(lead_type="internal_sales", name="Mine Lead", business_name="Mine Co", assigned_to=sdr, status="new")
        other = Lead.objects.create(lead_type="internal_sales", name="Other Lead", business_name="Other Co", assigned_to=other_sdr, status="new")
        unassigned = Lead.objects.create(lead_type="internal_sales", name="Unassigned Lead", business_name="Unassigned Co", status="new")

        self.client.force_login(sdr)
        dashboard = self.client.get(reverse("crm_home"))
        self.assertContains(dashboard, "Mine Co")
        self.assertNotContains(dashboard, "Other Co")
        self.assertNotContains(dashboard, "Unassigned Co")
        ops_dashboard = self.client.get(reverse("ops_dashboard"))
        self.assertContains(ops_dashboard, "Mine Co")
        self.assertNotContains(ops_dashboard, "Other Co")
        self.assertNotContains(ops_dashboard, "Unassigned Co")
        self.assertEqual(self.client.get(reverse("lead_detail", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[unassigned.pk])).status_code, 404)

        response = self.client.post(reverse("lead_create"), {
            "name": "Created by SDR",
            "business_name": "Forced Owner Co",
            "status": "new",
            "lead_temperature": "cold",
            "value": "0",
            "assigned_to": str(other_sdr.pk),
        })
        self.assertRedirects(response, reverse("crm_home"))
        self.assertEqual(Lead.objects.get(business_name="Forced Owner Co").assigned_to, sdr)

        self.client.force_login(admin)
        admin_dashboard = self.client.get(reverse("crm_home"))
        self.assertContains(admin_dashboard, "Mine Co")
        self.assertContains(admin_dashboard, "Other Co")
        self.assertContains(admin_dashboard, "Unassigned Co")

    def test_employee_can_bulk_upload_internal_sales_leads_csv(self):
        employee = User.objects.create_user(username="csv-ops", password="OpsPass123!", role="employee")
        other_sdr = User.objects.create_user(username="csv-other", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        response = self.client.get(reverse("lead_upload"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload leads from CSV or Excel")
        self.assertContains(self.client.get(reverse("crm_home")), reverse("lead_upload"))

        upload = SimpleUploadedFile(
            "leads.csv",
            (
                "name,business_name,industry,phone,email,source,status,notes,value,follow_up_date,assigned_to\n"
                "Ada Buyer,Ada Co,Home Services,555-1111,ada@example.com,CSV List,new,good interaction told me to leave an email,2500.00,2026-08-01,csv-other\n"
                "Ben Founder,Ben Studio,Med Spa,555-2222,ben@example.com,CSV List,follow_up,call back after 4,1200.50,,\n"
            ).encode(),
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        lead_import = LeadImport.objects.get(original_filename="leads.csv")
        self.assertRedirects(response, reverse("lead_import_detail", args=[lead_import.pk]))

        ada = Lead.objects.get(name="Ada Buyer")
        ben = Lead.objects.get(name="Ben Founder")
        self.assertEqual(ada.lead_type, "internal_sales")
        self.assertIsNone(ada.client)
        self.assertIsNone(ada.ai_instance)
        self.assertEqual(ada.assigned_to, employee)
        self.assertNotEqual(ada.assigned_to, other_sdr)
        self.assertEqual(ada.status, "email_requested")
        self.assertEqual(ada.lead_temperature, "warm")
        self.assertIn("Standardized outcome", ada.cleaned_notes)
        self.assertEqual(ben.status, "follow_up")
        self.assertEqual(ben.lead_temperature, "warm")
        self.assertEqual(LeadActivity.objects.filter(original_import=lead_import).count(), 2)
        self.assertEqual(Lead.objects.filter(lead_type="client_customer", name__in=["Ada Buyer", "Ben Founder"]).count(), 0)

    def test_csv_upload_validation_blocks_unusable_files(self):
        employee = User.objects.create_user(username="csv-ops-invalid", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        before = Lead.objects.count()
        upload = SimpleUploadedFile(
            "bad.csv",
            b"random,spreadsheet\nnot,a lead\n",
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import stopped. No leads were created.")
        self.assertContains(response, "headers were not recognized")
        self.assertEqual(Lead.objects.count(), before)

    @patch("crm.views.import_lead_file", side_effect=RuntimeError("simulated database failure"))
    def test_lead_upload_import_exception_shows_error_not_500(self, _importer):
        employee = User.objects.create_user(username="csv-ops-error", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        upload = SimpleUploadedFile(
            "valid.csv",
            b"name,business_name,phone\nPat,Failure Co,555-0000\n",
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The tracker could not be imported. No leads were saved.")
        self.assertContains(response, "run migrations on Render")

    def test_lead_upload_trims_long_values_for_postgres(self):
        employee = User.objects.create_user(username="csv-ops-long", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        long_website = "https://example.com/" + ("very-long-path/" * 25)
        upload = SimpleUploadedFile(
            "long-values.csv",
            (
                "name,business_name,phone,website,notes\n"
                f"Long Website Lead,Long Website Co,555-9191,{long_website},follow up later\n"
            ).encode(),
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload, "default_assigned_to": str(employee.pk)})
        lead_import = LeadImport.objects.get(original_filename="long-values.csv")
        self.assertRedirects(response, reverse("lead_import_detail", args=[lead_import.pk]))
        lead = Lead.objects.get(business_name="Long Website Co")
        self.assertEqual(lead.assigned_to, employee)
        self.assertLessEqual(len(lead.website), 200)
        self.assertLessEqual(len(lead.duplicate_key), 255)

    def test_sales_intelligence_rules_and_queues(self):
        employee = User.objects.create_user(username="queue-ops", password="OpsPass123!", role="employee")
        self.client.force_login(employee)
        classification = classify_sales_note("manager handles this and asked me to send info")
        self.assertEqual(classification.temperature, "warm")
        self.assertIn(classification.status, {"information_requested", "decision_maker_reached"})

        lead = Lead.objects.create(
            lead_type="internal_sales",
            business_name="Warm Demo Co",
            phone="555-3333",
            notes="call back after 4",
            status="callback_requested",
            lead_temperature="warm",
            cleaned_notes="The contact requested a callback after 4:00 PM.",
            assigned_to=employee,
        )
        response = self.client.get(reverse("crm_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SDR command center")
        self.assertContains(response, "Warm Demo Co")
        queue = self.client.get(reverse("lead_queue", args=["warm"]))
        self.assertContains(queue, "Warm Demo Co")
        detail = self.client.get(reverse("lead_detail", args=[lead.pk]) + "?draft=email")
        self.assertContains(detail, "Follow-up email draft")
        self.assertContains(detail, "Warm Demo Co")

    def test_xlsx_tracker_import_and_duplicate_review(self):
        employee = User.objects.create_user(username="xlsx-ops", password="OpsPass123!", role="employee")
        other_sdr = User.objects.create_user(username="xlsx-other", password="OpsPass123!", role="employee")
        Lead.objects.create(
            lead_type="internal_sales",
            business_name="Duplicate Co LLC",
            phone="(555) 444-0000",
            duplicate_key="duplicate|5554440000",
            assigned_to=other_sdr,
        )
        self.client.force_login(employee)
        workbook = build_minimal_xlsx([
            ["Business Name", "Phone", "Notes", "Assigned To"],
            ["Duplicate Co", "555-444-0000", "same company", "xlsx-ops"],
            ["Callback Spa", "555-555-1212", "call back after 4", "xlsx-ops"],
        ])
        upload = SimpleUploadedFile(
            "tracker.xlsx",
            workbook,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload})
        lead_import = LeadImport.objects.get(original_filename="tracker.xlsx")
        self.assertRedirects(response, reverse("lead_import_detail", args=[lead_import.pk]))
        duplicate = Lead.objects.get(business_name="Duplicate Co")
        callback = Lead.objects.get(business_name="Callback Spa")
        self.assertEqual(duplicate.status, "duplicate_review")
        self.assertTrue(duplicate.needs_review)
        self.assertEqual(duplicate.assigned_to, other_sdr)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[duplicate.pk])).status_code, 404)
        self.assertEqual(callback.status, "callback_requested")
        self.assertEqual(callback.lead_temperature, "warm")
        self.assertEqual(callback.assigned_to, employee)
        self.assertEqual(lead_import.sheet_names, ["Tracker"])
        self.assertEqual(lead_import.imported_count, 1)
        self.assertEqual(lead_import.updated_count, 1)
        self.assertGreaterEqual(lead_import.review_count, 1)

    def test_owner_or_admin_can_manage_staff_users(self):
        admin = User.objects.create_user(username="staff-admin", password="OpsPass123!", role="admin")
        self.client.force_login(admin)
        response = self.client.get(reverse("staff_users"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff & SDR accounts")

        response = self.client.post(reverse("staff_user_create"), {
            "first_name": "Kaitlyn",
            "last_name": "Bonilla",
            "role": "employee",
            "is_active": "on",
            "password": "AIBG123",
        })
        self.assertRedirects(response, reverse("staff_users"))
        kaitlyn = User.objects.get(username="kaitlyn@aibiz.guru")
        self.assertEqual(kaitlyn.email, "kaitlyn@aibiz.guru")
        self.assertEqual(kaitlyn.role, "employee")
        self.assertTrue(kaitlyn.is_staff)
        self.assertTrue(kaitlyn.check_password("AIBG123"))

        response = self.client.post(reverse("staff_user_deactivate", args=[kaitlyn.pk]))
        self.assertRedirects(response, reverse("staff_users"))
        kaitlyn.refresh_from_db()
        self.assertFalse(kaitlyn.is_active)

    def test_admin_can_assign_upload_view_sdr_kpis_and_delete_lead(self):
        admin = User.objects.create_user(username="lead-admin", password="OpsPass123!", role="admin")
        sdr = User.objects.create_user(
            username="kpi-sdr@aibiz.guru",
            email="kpi-sdr@aibiz.guru",
            password="OpsPass123!",
            role="employee",
            first_name="KPI",
            last_name="SDR",
        )
        self.client.force_login(admin)
        upload_page = self.client.get(reverse("lead_upload"))
        self.assertContains(upload_page, "Who should own these leads?")
        self.assertContains(upload_page, "Assign this upload to")

        upload = SimpleUploadedFile(
            "assigned.csv",
            (
                "name,business_name,industry,phone,email,status,notes\n"
                "Casey Contact,KPI Test Co,Home Services,555-7777,casey@example.com,new,send info and call back tomorrow\n"
            ).encode(),
            content_type="text/csv",
        )
        response = self.client.post(reverse("lead_upload"), {"csv_file": upload, "default_assigned_to": str(sdr.pk)})
        lead_import = LeadImport.objects.get(original_filename="assigned.csv")
        self.assertRedirects(response, reverse("lead_import_detail", args=[lead_import.pk]))
        lead = Lead.objects.get(business_name="KPI Test Co")
        self.assertEqual(lead.assigned_to, sdr)

        staff_list = self.client.get(reverse("staff_users"))
        self.assertContains(staff_list, reverse("staff_performance", args=[sdr.pk]))
        performance = self.client.get(reverse("staff_performance", args=[sdr.pk]))
        self.assertEqual(performance.status_code, 200)
        self.assertContains(performance, "SDR Performance")
        self.assertContains(performance, "KPI Test Co")
        self.assertContains(performance, "Contact Rate")

        detail = self.client.get(reverse("lead_detail", args=[lead.pk]))
        self.assertContains(detail, reverse("lead_delete", args=[lead.pk]))
        response = self.client.post(reverse("lead_delete", args=[lead.pk]))
        self.assertRedirects(response, reverse("crm_home"))
        lead.refresh_from_db()
        self.assertTrue(lead.archived)
        self.assertEqual(self.client.get(reverse("lead_detail", args=[lead.pk])).status_code, 404)

    def test_staff_messaging_owner_oversight_and_group_messages(self):
        owner = User.objects.create_user(username="msg-owner", password="OwnerPass123!", role="owner")
        alice = User.objects.create_user(username="alice@aibiz.guru", password="OpsPass123!", role="employee", first_name="Alice")
        bob = User.objects.create_user(username="bob@aibiz.guru", password="OpsPass123!", role="employee", first_name="Bob")
        charlie = User.objects.create_user(username="charlie@aibiz.guru", password="OpsPass123!", role="employee", first_name="Charlie")

        self.client.force_login(alice)
        response = self.client.get(reverse("staff_messages"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "team-chat-widget")
        response = self.client.post(reverse("staff_message_create"), {
            "title": "",
            "participants": [str(bob.pk)],
            "message": "Can you follow up with the HVAC lead?",
        })
        thread = StaffMessageThread.objects.get()
        self.assertRedirects(response, reverse("staff_message_thread", args=[thread.pk]))
        self.assertEqual(thread.messages.count(), 1)
        self.assertFalse(thread.is_group)

        self.client.force_login(bob)
        summary = self.client.get(reverse("staff_message_summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["unread_count"], 1)
        self.assertEqual(summary.json()["threads"][0]["unread_count"], 1)
        bob_view = self.client.get(reverse("staff_message_thread", args=[thread.pk]))
        self.assertEqual(bob_view.status_code, 200)
        self.assertContains(bob_view, "Can you follow up")
        self.assertEqual(self.client.get(reverse("staff_message_summary")).json()["unread_count"], 0)

        self.client.force_login(charlie)
        self.assertEqual(self.client.get(reverse("staff_message_thread", args=[thread.pk])).status_code, 404)

        self.client.force_login(owner)
        owner_view = self.client.get(reverse("staff_message_thread", args=[thread.pk]))
        self.assertEqual(owner_view.status_code, 200)
        self.assertContains(owner_view, "Owner Oversight")
        feed = self.client.get(reverse("staff_message_feed", args=[thread.pk]))
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(feed.json()["messages"][0]["body"], "Can you follow up with the HVAC lead?")

        response = self.client.post(reverse("staff_message_thread", args=[thread.pk]), {"body": "Loop me in if this gets hot."})
        self.assertRedirects(response, reverse("staff_message_thread", args=[thread.pk]))
        self.assertTrue(StaffMessage.objects.filter(thread=thread, sender=owner, body__icontains="Loop me in").exists())

        response = self.client.post(reverse("staff_message_create"), {
            "title": "Ops group",
            "participants": [str(alice.pk), str(bob.pk), str(charlie.pk)],
            "message": "Morning team — post updates here.",
        })
        group = StaffMessageThread.objects.get(title="Ops group")
        self.assertRedirects(response, reverse("staff_message_thread", args=[group.pk]))
        self.assertTrue(group.is_group)
        self.assertEqual(group.participants.count(), 4)

    def test_staff_messages_support_attachments_and_secure_downloads(self):
        owner = User.objects.create_user(username="file-owner", password="OwnerPass123!", role="owner")
        alice = User.objects.create_user(username="file-alice@aibiz.guru", password="OpsPass123!", role="employee", first_name="Alice")
        bob = User.objects.create_user(username="file-bob@aibiz.guru", password="OpsPass123!", role="employee", first_name="Bob")
        outsider = User.objects.create_user(username="file-outsider@aibiz.guru", password="OpsPass123!", role="employee", first_name="Outsider")

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            self.client.force_login(alice)
            upload = SimpleUploadedFile("lead-notes.pdf", b"fake pdf bytes", content_type="application/pdf")
            response = self.client.post(reverse("staff_message_create"), {
                "title": "File test",
                "participants": [str(bob.pk)],
                "message": "Here is the lead document ✅",
                "attachments": upload,
            })
            thread = StaffMessageThread.objects.get(title="File test")
            self.assertRedirects(response, reverse("staff_message_thread", args=[thread.pk]))
            attachment = StaffMessageAttachment.objects.get()
            self.assertEqual(attachment.original_filename, "lead-notes.pdf")
            self.assertEqual(attachment.uploaded_by, alice)

            thread_view = self.client.get(reverse("staff_message_thread", args=[thread.pk]))
            self.assertContains(thread_view, "lead-notes.pdf")
            self.assertContains(thread_view, "📎")

            download = self.client.get(reverse("staff_message_attachment", args=[attachment.pk]))
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["Content-Disposition"], 'attachment; filename="lead-notes.pdf"')

            self.client.force_login(outsider)
            self.assertEqual(self.client.get(reverse("staff_message_attachment", args=[attachment.pk])).status_code, 404)

            self.client.force_login(owner)
            owner_download = self.client.get(reverse("staff_message_attachment", args=[attachment.pk]))
            self.assertEqual(owner_download.status_code, 200)

            self.client.force_login(bob)
            reply_file = SimpleUploadedFile("reply.csv", b"name,value\nA,1\n", content_type="text/csv")
            response = self.client.post(reverse("staff_message_thread", args=[thread.pk]), {"body": "", "attachments": reply_file})
            self.assertRedirects(response, reverse("staff_message_thread", args=[thread.pk]))
            self.assertTrue(StaffMessage.objects.filter(thread=thread, body="📎 Sent attachment").exists())
            self.assertEqual(StaffMessageAttachment.objects.count(), 2)

    def test_staff_time_clock_and_owner_admin_visibility(self):
        admin = User.objects.create_user(username="clock-admin", password="OpsPass123!", role="admin")
        employee = User.objects.create_user(username="clock-employee", password="OpsPass123!", role="employee", first_name="Clock", last_name="Employee")

        self.client.force_login(employee)
        response = self.client.get(reverse("staff_time_clock"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Clock in")
        response = self.client.post(reverse("staff_time_clock"), {"action": "clock_in", "note": "Starting outreach block"})
        self.assertRedirects(response, reverse("staff_time_clock"))
        entry = TimeClockEntry.objects.get(employee=employee)
        self.assertIsNone(entry.clock_out)
        self.assertEqual(entry.note, "Starting outreach block")

        response = self.client.post(reverse("staff_time_clock"), {"action": "clock_out", "note": "Finished outreach block"})
        self.assertRedirects(response, reverse("staff_time_clock"))
        entry.refresh_from_db()
        self.assertIsNotNone(entry.clock_out)
        self.assertEqual(entry.note, "Finished outreach block")

        self.client.force_login(admin)
        admin_view = self.client.get(reverse("staff_time_clock_admin"))
        self.assertEqual(admin_view.status_code, 200)
        self.assertContains(admin_view, "Team Time Clock")
        self.assertContains(admin_view, "Clock Employee")
        performance = self.client.get(reverse("staff_performance", args=[employee.pk]))
        self.assertEqual(performance.status_code, 200)
        self.assertContains(performance, "Time Clock")
        self.assertContains(performance, "Hours / 7 days")

    @override_settings(PLATFORM_OPENAI_API_KEY="", OPENAI_DAILY_USAGE_LIMIT=500)
    def test_shared_ai_service_missing_key_records_fallback(self):
        from assistant_ai.services import PlatformAIService

        service = PlatformAIService(assistant_role="sdr_assistant")
        reply, meta = service.chat(messages=[{"role": "user", "content": "hello"}], fallback="offline")
        self.assertEqual(reply, "offline")
        self.assertEqual(meta["reason"], "missing_api_key")
        record = UsageRecord.objects.get(assistant_role="sdr_assistant")
        self.assertEqual(record.status, "fallback")
        self.assertEqual(record.error_code, "missing_api_key")

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
            "/admin/crm/leadimport/",
            "/admin/crm/leadactivity/",
            "/admin/assistant_ai/assistantrole/",
            "/admin/assistant_ai/usagerecord/",
            "/admin/audit/activitylog/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertTrue(AssistantRole.objects.filter(key="sdr_assistant").exists())

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
