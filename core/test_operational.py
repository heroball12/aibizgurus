from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from assistant_ai.models import Conversation, Message, UsageRecord
from audit.forms import StaffUserForm
from billing.models import BillingCustomer, BillingEvent
from clients.models import ClientAccount, AIInstance, BusinessProfile
from core.models import IndustryTemplate, RequestBudget, ConsultationRequest
from core.rate_limits import consume_budget
from core.seed import seed_industries
from crm.models import Lead, LeadGenerationBatch, LeadStaging
from crm.lead_finder import OpenStreetMapProvider, get_lead_providers, generate_leads_for_batch
from voice.models import CallLog, SMSLog

User = get_user_model()


@override_settings(PLATFORM_OPENAI_API_KEY="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", VALIDATE_TWILIO_SIGNATURES=False)
class OperationalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="operational-client", email="sample@example.test", password="Client-Unique-2026!")
        cls.account = ClientAccount.objects.create(user=cls.user, business_name="Sample Comfort", activation_status="active", contact_email="sample@example.test")
        cls.ai = AIInstance.objects.create(client=cls.account, name="Sample Assistant", status="active", embed_enabled=True, voice_enabled=True, sms_enabled=True, collect_name=True, collect_phone=True, collect_email=True, openai_api_mode="fallback")
        BusinessProfile.objects.create(client=cls.account, hours="Monday–Friday 8am–5pm")

    def chat(self, **values):
        return self.client.post(reverse("widget_chat_api", args=[self.ai.slug]), {"message": "I need a quote", **values})

    def test_conversation_requires_signed_ownership_and_deduplicates_lead(self):
        first = self.chat(name="Alex", phone="619-555-0100").json()
        self.assertEqual(Lead.objects.count(), 1)
        rejected = self.chat(conversation_id=first["conversation_id"], visitor_id="pretend-owner")
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(self.chat(conversation_token=first["conversation_token"] + "tampered").status_code, 403)
        second = self.chat(conversation_token=first["conversation_token"], message="Please book an appointment", email="alex@example.test")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        lead = Lead.objects.get()
        self.assertEqual(lead.email, "alex@example.test")
        self.assertEqual(lead.phone, "619-555-0100")
        self.assertEqual(lead.conversation_id, first["conversation_id"])

    def test_signed_chat_cannot_cross_assistants(self):
        first = self.chat().json()
        other = AIInstance.objects.create(client=self.account, name="Second", status="active", embed_enabled=True, openai_api_mode="fallback")
        response = self.client.post(reverse("widget_chat_api", args=[other.slug]), {"message":"hello", "conversation_token":first["conversation_token"]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_chat_limits_and_contact_flags(self):
        self.assertEqual(self.chat(message="x" * 2001).status_code, 400)
        self.assertEqual(self.chat(email="invalid email").status_code, 400)
        self.ai.collect_email = False
        self.ai.save()
        response = self.chat(email="private@example.test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Conversation.objects.get().customer_email, "")
        with patch("assistant_ai.views.consume_budget", return_value=False):
            self.assertEqual(self.chat().status_code, 429)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_chat_notification_includes_initial_contact(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.chat(name="Sample Alex", phone="619-555-0101")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("619-555-0101", mail.outbox[0].body)
        self.assertIn("I need a quote", mail.outbox[0].body)

    def test_widget_hours_fallback_uses_business_knowledge(self):
        response = self.chat(message="What are your hours?")
        self.assertIn("8am–5pm", response.json()["reply"])

    def test_demo_fallback_is_public_isolated_and_explicit(self):
        response = self.client.post(reverse("demo_chat"), {"scenario":"home-services", "message":"Can I book a visit?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "guided")
        self.assertIn("no real booking", response.json()["reply"])
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(Lead.objects.exists())
        self.assertEqual(self.client.post(reverse("demo_chat"), {"scenario":"invalid", "message":"hello"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("demo_chat"), {"scenario":"dental", "message":"x"*1001}).status_code, 400)

    def test_demo_csrf_and_reset(self):
        protected = Client(enforce_csrf_checks=True)
        self.assertEqual(protected.post(reverse("demo_chat"), {"scenario":"dental", "message":"hello"}).status_code, 403)
        page = protected.get(reverse("demo"))
        self.assertContains(page, "demo-workflow.mp4")
        token = protected.cookies["csrftoken"].value
        self.assertEqual(protected.post(reverse("demo_chat"), {"scenario":"dental", "message":"hello"}, HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertIn("dental", protected.session["demo_history"])
        protected.post(reverse("demo_chat"), {"scenario":"dental", "reset":"1"}, HTTP_X_CSRFTOKEN=token)
        self.assertNotIn("dental", protected.session["demo_history"])

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    @patch("assistant_ai.services.OpenAI")
    def test_public_demo_uses_live_gateway_with_strict_sample_context(self, mock_ai):
        completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="What day works for your sample request?"))], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=9, total_tokens=19))
        mock_ai.return_value.chat.completions.create.return_value = completion
        response = self.client.post(reverse("demo_chat"), {"scenario":"dental", "message":"I need a cleaning"})
        self.assertEqual(response.json()["mode"], "ai")
        self.assertEqual(UsageRecord.objects.get().assistant_role, "public_demo")
        kwargs = mock_ai.return_value.chat.completions.create.call_args.kwargs
        self.assertIn("Nova Care", kwargs["messages"][0]["content"])
        self.assertIn("fictional business", kwargs["messages"][0]["content"])
        self.assertIn("administrative questions", kwargs["messages"][0]["content"])
        self.assertEqual(kwargs["max_completion_tokens"], 600)
        self.assertFalse(Lead.objects.exists())

    def test_shared_budget_and_expired_cleanup(self):
        RequestBudget.objects.create(key="expired", expires_at=timezone.now()-timedelta(seconds=1))
        self.assertTrue(consume_budget("test", "same-user", limit=1))
        self.assertFalse(consume_budget("test", "same-user", limit=1))
        self.assertFalse(RequestBudget.objects.filter(key="expired").exists())
        self.assertTrue(consume_budget("test", "another-user", limit=1))

    def test_sms_retries_and_followups_share_one_conversation_and_lead(self):
        url = reverse("incoming_sms", args=[self.ai.slug])
        data = {"MessageSid":"SMsample1", "From":"+16195550100", "To":"+16195550101", "Body":"I need a quote"}
        first = self.client.post(url, data)
        self.assertEqual(first.status_code, 200)
        retry = self.client.post(url, data)
        self.assertEqual(first.content, retry.content)
        self.assertEqual(SMSLog.objects.count(), 1)
        self.client.post(url, {**data,"MessageSid":"SMsample2","Body":"Tomorrow morning please"})
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 4)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_voice_retains_turn_history_and_replays_retry_response(self):
        url = reverse("incoming_call", args=[self.ai.slug])
        data = {"CallSid":"CAsample", "From":"+16195550100", "To":"+16195550101"}
        self.client.post(url, data); self.client.post(url, data)
        self.assertEqual(CallLog.objects.count(), 1)
        call = CallLog.objects.get()
        url = reverse("process_call", args=[self.ai.slug, call.pk])
        first = self.client.post(url + "?turn=0", {**data, "SpeechResult":"I need a quote"})
        retry = self.client.post(url + "?turn=0", {**data, "SpeechResult":"I need a quote"})
        self.assertEqual(first.content, retry.content)
        self.client.post(url + "?turn=1", {**data, "SpeechResult":"For tomorrow please"})
        call.refresh_from_db()
        self.assertEqual(call.conversation.messages.count(), 4)
        self.assertIn("Assistant:", call.transcript)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(self.client.post(url, {"CallSid":"other"}).status_code, 403)

    @override_settings(VALIDATE_TWILIO_SIGNATURES=True, TWILIO_AUTH_TOKEN="test-token")
    def test_twilio_signature_required(self):
        url = reverse("incoming_sms", args=[self.ai.slug])
        data = {"MessageSid":"SMverified", "From":"+16195550100", "Body":"hello"}
        self.assertEqual(self.client.post(url, data).status_code, 403)
        from twilio.request_validator import RequestValidator
        signature = RequestValidator("test-token").compute_signature("http://testserver" + url, data)
        self.assertEqual(self.client.post(url, data, HTTP_X_TWILIO_SIGNATURE=signature).status_code, 200)

    def test_client_counts_and_export_are_scoped(self):
        for i in range(12): Lead.objects.create(client=self.account, lead_type="client_customer", name=f"Person {i}")
        other_user = User.objects.create_user(username="other-client")
        other_account = ClientAccount.objects.create(user=other_user, business_name="Other Customer")
        Lead.objects.create(client=other_account, lead_type="client_customer", name="Must stay private")
        Lead.objects.create(client=self.account, lead_type="client_customer", name="=1+1")
        self.client.force_login(self.user)
        response = self.client.get(reverse("portal_home"))
        self.assertEqual(response.context["lead_count"], 13)
        export = self.client.get(reverse("client_leads_export"))
        self.assertNotIn("Must stay private", export.content.decode())
        self.assertIn("'=1+1", export.content.decode())

    def test_staff_form_rejects_shared_or_missing_password(self):
        base = {"first_name":"New", "last_name":"Staff", "role":"employee", "is_active":True}
        self.assertFalse(StaffUserForm(base).is_valid())
        self.assertFalse(StaffUserForm({**base,"password":"AIBG123"}).is_valid())
        self.assertTrue(StaffUserForm({**base,"password":"UniqueStaff-Password2026!"}).is_valid())

    def test_legacy_password_requires_change_and_logout_requires_post(self):
        staff = User.objects.create_user(username="legacy",role="employee",password="AIBG123")
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(reverse("ops_dashboard")), reverse("password_change"))
        response = self.client.post(reverse("password_change"), {"old_password":"AIBG123", "new_password1":"New-Unique-Password2026!", "new_password2":"New-Unique-Password2026!"})
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("home"))

    def test_password_reset_sends_link_and_login_honors_safe_next(self):
        self.client.post(reverse("password_reset"), {"email":self.user.email})
        self.assertEqual(len(mail.outbox),1)
        self.assertIn("/accounts/reset/",mail.outbox[0].body)
        response = self.client.post(reverse("login")+"?next=/portal/conversations/", {"username":self.user.username,"password":"Client-Unique-2026!"})
        self.assertRedirects(response, reverse("client_conversations"))

    def test_seed_preserves_customized_industry(self):
        item = IndustryTemplate.objects.first()
        item.summary = "Owner-customized summary"
        item.save()
        seed_industries(); item.refresh_from_db()
        self.assertEqual(item.summary,"Owner-customized summary")
        seed_industries(force=True); item.refresh_from_db()
        self.assertNotEqual(item.summary,"Owner-customized summary")

    def test_health_detects_unavailable_database(self):
        with patch.object(connection, "cursor", side_effect=OperationalError("test-only")):
            response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),{"status":"unavailable"})

    def test_assessment_form_persists_one_request_and_one_crm_lead(self):
        response = self.client.post(reverse("growth_assessment"), {"name":"Sample", "email":"sample@example.test", "industry":"HVAC", "business_name":"Sample Business", "message":"I would like a demo"})
        self.assertRedirects(response,reverse("growth_assessment"))
        self.assertEqual(ConsultationRequest.objects.count(),1)
        self.assertEqual(Lead.objects.filter(source="AI Business Growth Assessment").count(),1)

    @override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=False, LEAD_FINDER_ENABLE_FALLBACK_PROVIDER=True)
    def test_lead_finder_never_fills_with_fake_rows(self):
        self.assertEqual([p.name for p in get_lead_providers()],["openstreetmap"])
        batch = LeadGenerationBatch.objects.create(employee=self.user, industry="HVAC",location="San Diego, CA",quantity_requested=5)
        generate_leads_for_batch(batch.pk); batch.refresh_from_db()
        self.assertEqual(batch.status,"failed")
        self.assertEqual(LeadStaging.objects.count(),0)

    @override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=True)
    @patch("crm.lead_finder.request.urlopen")
    def test_real_listing_query_scopes_city_to_state(self, urlopen):
        import json
        from urllib.parse import parse_qs
        response = MagicMock(); response.read.return_value=json.dumps({"elements":[{"tags":{"name":"Verified Sample Listing","phone":"6195550100","addr:city":"San Diego"}}]}).encode()
        urlopen.return_value.__enter__.return_value=response
        rows=OpenStreetMapProvider().search(industry="HVAC",location="San Diego, CA",limit=5)
        self.assertEqual(rows[0].business_name,"Verified Sample Listing")
        query=parse_qs(urlopen.call_args.args[0].data.decode())["data"][0]
        self.assertIn('"ISO3166-2"="US-CA"',query)
        self.assertIn('rel(area.region)',query)
        self.assertIn('map_to_area',query)
        self.assertNotIn('area["name"="San Diego, CA"]',query)

    def test_already_running_generation_is_not_run_twice(self):
        batch=LeadGenerationBatch.objects.create(employee=self.user,industry="HVAC",quantity_requested=5,status="searching")
        with patch("crm.lead_finder.get_lead_providers") as provider:
            generate_leads_for_batch(batch.pk)
            provider.assert_not_called()

    def test_staff_edit_without_password_keeps_existing_password(self):
        staff=User.objects.create_user(username="jamie@aibiz.guru",first_name="Jamie",role="employee",password="Original-Unique-2026!")
        form=StaffUserForm({"first_name":"Jamie","last_name":"Updated","role":"employee","is_active":True,"password":""},instance=staff)
        self.assertTrue(form.is_valid(),form.errors)
        form.save();staff.refresh_from_db()
        self.assertTrue(staff.check_password("Original-Unique-2026!"))
        self.assertEqual(staff.last_name,"Updated")

    @override_settings(TRUSTED_PROXY_HOPS=1)
    def test_proxy_identity_ignores_spoofed_leftmost_address(self):
        from core.rate_limits import request_identity
        from django.test import RequestFactory
        request=RequestFactory().get("/",HTTP_X_FORWARDED_FOR="198.51.100.55, 203.0.113.22")
        self.assertEqual(request_identity(request),"203.0.113.22")
        with override_settings(TRUSTED_PROXY_HOPS=0):
            self.assertEqual(request_identity(request),"127.0.0.1")

    def test_authentication_rate_limit_returns_retry_after(self):
        with patch("core.rate_limits.consume_budget",return_value=False):
            response=self.client.post(reverse("login"),{"username":"guess","password":"incorrect"})
        self.assertEqual(response.status_code,429)
        self.assertEqual(response["Retry-After"],"900")

    def test_legacy_sample_batch_cannot_be_promoted(self):
        from crm.lead_finder import convert_staging_to_crm_lead
        batch=LeadGenerationBatch.objects.create(employee=self.user,industry="HVAC",quantity_requested=5,provider_summary={"fallback_directory":10})
        row=LeadStaging.objects.create(batch=batch,business_name="Legacy sample",phone_number="6195550100",industry="HVAC",created_by=self.user)
        with self.assertRaisesMessage(ValueError,"generated sample data"):
            convert_staging_to_crm_lead(row,employee=self.user)
        self.assertTrue(LeadStaging.objects.filter(pk=row.pk).exists())
        self.assertFalse(Lead.objects.exists())

    def test_hidden_workbook_sheets_are_not_imported(self):
        import io,zipfile
        from core.tests import build_minimal_xlsx
        from crm.importers import parse_xlsx_file
        original=build_minimal_xlsx([["Business Name","Phone"],["Hidden Contact","6195550100"]])
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source,zipfile.ZipFile(output,"w") as target:
            for name in source.namelist():
                content=source.read(name)
                if name=="xl/workbook.xml":content=content.replace(b'<sheet name=',b'<sheet state="hidden" name=')
                target.writestr(name,content)
        parsed=parse_xlsx_file(SimpleUploadedFile("hidden.xlsx",output.getvalue()))
        self.assertFalse(parsed.rows)
        self.assertTrue(parsed.errors)
