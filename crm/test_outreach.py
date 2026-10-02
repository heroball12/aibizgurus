import base64
import json
import time
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from twilio.request_validator import RequestValidator

from core.security import encrypt_value, decrypt_value
from .models import (
    Lead,
    LeadActivity,
    OutreachMessage,
    StaffMailbox,
    SalesSMSContact,
    SalesSMSReply,
)
from .outreach import SMS_FOOTER, message_data
from .outreach_providers import GMAIL_SCOPE, OutreachError, phone_number, send_gmail

CONFIG = dict(
    SALES_GOOGLE_CLIENT_ID="test-client",
    SALES_GOOGLE_CLIENT_SECRET="test-secret",
    SALES_GOOGLE_REDIRECT_URI="https://aibiz.guru/crm/outreach/google/callback/",
    SALES_GOOGLE_DOMAINS=["aibiz.guru"],
    FIELD_ENCRYPTION_KEY="unit-test-encryption-key",
    PUBLIC_BASE_URL="https://aibiz.guru",
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_AUTH_TOKEN="test-auth",
    SALES_SMS_FROM_NUMBER="+16195550100",
    SALES_SMS_MESSAGING_SERVICE_SID="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


# The retired transport implementation is exercised only through this test URLconf.
# Production URLs return 410; SalesEmailTests verifies that no transport is reachable.
from django.urls import path, include
from config.urls import urlpatterns as production_patterns
from . import outreach_views as legacy
urlpatterns = [path('crm/', include([
    path('outreach/',legacy.connections,name='outreach_connections'),
    path('outreach/google/connect/',legacy.google_connect,name='outreach_google_connect'),
    path('outreach/google/callback/',legacy.google_callback,name='outreach_google_callback'),
    path('outreach/google/disconnect/',legacy.google_disconnect,name='outreach_google_disconnect'),
    path('leads/<int:pk>/outreach/draft/',legacy.draft,name='outreach_draft'),
    path('outreach/<uuid:pk>/send/',legacy.send,name='outreach_send'),
    path('outreach/<uuid:pk>/status/',legacy.status,name='outreach_status'),
    path('outreach/sms/inbound/',legacy.sms_inbound,name='outreach_sms_inbound'),
    path('outreach/sms/<uuid:pk>/status/',legacy.sms_status,name='outreach_sms_status'),
]))] + production_patterns

@override_settings(ROOT_URLCONF=__name__, **CONFIG)
class OutreachTests(TestCase):
    def setUp(self):
        self.rep = get_user_model().objects.create_user(
            username="sales", role="employee", first_name="Erika"
        )
        self.other = get_user_model().objects.create_user(
            username="other-sales", role="employee"
        )
        self.lead = Lead.objects.create(
            business_name="Aster HVAC",
            phone="619-555-0199",
            email="owner@example.com",
            assigned_to=self.rep,
            notes="Owner wants help with missed calls.",
            assessment_brief={"pricing": "private-pricing"},
        )
        self.mailbox = StaffMailbox.objects.create(
            user=self.rep,
            email="erika@aibiz.guru",
            google_subject="google-123",
            refresh_token=encrypt_value("test-refresh"),
            scopes=GMAIL_SCOPE,
        )
        self.client.force_login(self.rep)

    def draft(self, channel="email"):
        return OutreachMessage.objects.create(
            lead=self.lead,
            employee=self.rep,
            channel=channel,
            recipient=self.lead.email if channel == "email" else "+16195550199",
            sender=(
                self.mailbox.email
                if channel == "email"
                else CONFIG["SALES_SMS_FROM_NUMBER"]
            ),
            subject="Your next step",
            body="Hi, Erika from AI Business Gurus. Ready for a Growth Assessment? "
            + SMS_FOOTER,
        )

    def send(self, message, **updates):
        payload = {
            "confirmed": True,
            "sms_consent": True,
            "subject": message.subject,
            "body": message.body,
            **updates,
        }
        return self.client.post(
            reverse("outreach_send", args=[message.pk]),
            json.dumps(payload),
            content_type="application/json",
        )

    def test_generation_is_contextual_and_never_sends(self):
        with patch(
            "crm.outreach.PlatformAIService.structured_json",
            return_value=(
                {
                    "subject": "Missed calls at Aster",
                    "body": "Hi, can we discuss missed calls?",
                },
                {"status": "success"},
            ),
        ) as ai, patch("crm.outreach.send_gmail") as transport:
            response = self.client.post(
                reverse("outreach_draft", args=[self.lead.pk]),
                json.dumps({"channel": "email"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(OutreachMessage.objects.get().status, "draft")
        self.assertIn("missed calls", ai.call_args.kwargs["messages"][1]["content"])
        self.assertNotIn(
            "private-pricing", ai.call_args.kwargs["messages"][1]["content"]
        )
        self.assertIn(
            "ONLY AI Specialists", ai.call_args.kwargs["messages"][0]["content"]
        )
        transport.assert_not_called()
        self.assertEqual(LeadActivity.objects.count(), 0)

    def test_ai_failure_never_masquerades_as_generated_copy(self):
        for result in [
            ({}, {"status": "fallback"}),
            ([], {"status": "success"}),
            ({"subject": "x", "body": True}, {"status": "success"}),
        ]:
            with patch(
                "crm.outreach.PlatformAIService.structured_json", return_value=result
            ):
                response = self.client.post(
                    reverse("outreach_draft", args=[self.lead.pk]),
                    '{"channel":"email"}',
                    content_type="application/json",
                )
            self.assertIn(response.status_code, [400, 503])
        self.assertEqual(OutreachMessage.objects.count(), 0)

    def test_approved_edits_send_once_and_are_logged_exactly(self):
        message = self.draft()
        edited = "Hi Sam,\nCan we review your missed-call process on a 15–20 minute video call?\nErika"
        with patch(
            "crm.outreach.send_gmail", return_value=("gmail-id", "submitted")
        ) as provider:
            response = self.send(message, body=edited, subject="Aster operations")
            again = self.send(message, body="different body")
        self.assertEqual(response.json()["status"], "sent")
        self.assertEqual(again.json()["body"], edited)
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[0].body, edited)
        self.assertEqual(LeadActivity.objects.count(), 1)
        self.assertIn(edited, LeadActivity.objects.get().raw_note)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "attempted")
        self.assertIsNotNone(self.lead.last_contact_at)

    def test_unapproved_invalid_and_priced_content_is_blocked(self):
        message = self.draft()
        with patch("crm.outreach.send_gmail") as provider:
            for payload in [
                {"confirmed": False},
                {"subject": "inject\r\nBcc: other@example.com"},
                {"body": ""},
                {"body": "Our price is $99."},
            ]:
                self.assertEqual(self.send(message, **payload).status_code, 400)
        provider.assert_not_called()

    def test_scope_and_recipient_rechecked_at_send(self):
        message = self.draft()
        self.lead.email = "new@example.com"
        self.lead.save()
        with patch("crm.outreach.send_gmail") as provider:
            self.assertEqual(self.send(message).status_code, 400)
            self.lead.email = message.recipient
            self.lead.status = "do_not_contact"
            self.lead.save()
            self.assertEqual(self.send(message).status_code, 400)
            self.lead.assigned_to = self.other
            self.lead.save()
            self.assertEqual(self.send(message).status_code, 404)
        provider.assert_not_called()
        self.client.force_login(self.other)
        self.assertEqual(self.send(message).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("outreach_status", args=[message.pk])).status_code,
            404,
        )

    def test_business_closure_evidence_blocks_reviewed_outreach(self):
        message = self.draft()
        self.lead.business_verification = {"status": "needs_review"}
        self.lead.save(update_fields=["business_verification"])
        with patch("crm.outreach.send_gmail") as provider:
            self.assertEqual(self.send(message).status_code, 400)
        provider.assert_not_called()

    def test_sender_changes_expired_drafts_and_missing_connection_block(self):
        message = self.draft()
        self.mailbox.email = "changed@aibiz.guru"
        self.mailbox.save()
        self.assertEqual(self.send(message).status_code, 400)
        self.mailbox.email = message.sender
        self.mailbox.save()
        OutreachMessage.objects.filter(pk=message.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        self.assertEqual(self.send(message).status_code, 400)
        self.mailbox.delete()
        self.assertEqual(self.send(self.draft()).status_code, 400)

    def test_uncertain_and_definitive_failures_never_auto_retry(self):
        for uncertain, expected in [(True, "unknown"), (False, "failed")]:
            message = self.draft()
            with patch(
                "crm.outreach.send_gmail",
                side_effect=OutreachError("Check provider", uncertain=uncertain),
            ) as provider:
                self.assertEqual(self.send(message).json()["status"], expected)
                self.assertEqual(self.send(message).json()["status"], expected)
            provider.assert_called_once()
        self.assertEqual(LeadActivity.objects.count(), 0)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.last_contact_at)

    def test_stale_sending_is_uncertain_and_resending_blocked(self):
        message = self.draft()
        message.status = "sending"
        message.approved_at = timezone.now() - timedelta(minutes=3)
        message.save()
        self.assertEqual(message_data(message)["status"], "unknown")
        with patch("crm.outreach.send_gmail") as provider:
            self.assertEqual(self.send(message).json()["status"], "unknown")
        provider.assert_not_called()

    def test_csrf_post_and_employee_access(self):
        message = self.draft()
        self.assertEqual(
            self.client.get(reverse("outreach_send", args=[message.pk])).status_code,
            405,
        )
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.rep)
        self.assertEqual(
            strict.post(reverse("outreach_send", args=[message.pk]), {}).status_code,
            403,
        )
        customer = get_user_model().objects.create_user(
            username="customer", role="client"
        )
        self.client.force_login(customer)
        self.assertEqual(
            self.client.get(reverse("outreach_connections")).status_code, 302
        )

    def test_sms_requires_consent_brand_and_footer_and_respects_optout(self):
        message = self.draft("sms")
        with patch(
            "crm.outreach.send_sms", return_value=("SMone", "queued")
        ) as provider:
            self.assertEqual(self.send(message, sms_consent=False).status_code, 400)
            self.assertEqual(self.send(message, body="Hello").status_code, 400)
            SalesSMSContact.objects.create(phone=message.recipient, opted_out=True)
            self.assertEqual(self.send(message).status_code, 400)
            SalesSMSContact.objects.all().delete()
            self.assertEqual(self.send(message).json()["delivery_status"], "queued")
        provider.assert_called_once()
        self.assertTrue(LeadActivity.objects.get().metadata["sms_consent_confirmed"])

    def signed_post(self, name, data, args=None):
        url = reverse(name, args=args)
        data = {"AccountSid": CONFIG["TWILIO_ACCOUNT_SID"], **data}
        signature = RequestValidator(CONFIG["TWILIO_AUTH_TOKEN"]).compute_signature(
            CONFIG["PUBLIC_BASE_URL"] + url, data
        )
        return self.client.post(url, data, HTTP_X_TWILIO_SIGNATURE=signature)

    def test_sms_status_callbacks_verified_monotonic_and_idempotent(self):
        message = self.draft("sms")
        with patch("crm.outreach.send_sms", return_value=("SMone", "queued")):
            self.send(message)
        data = {
            "MessageSid": "SMone",
            "To": message.recipient,
            "From": message.sender,
            "MessageStatus": "delivered",
        }
        self.assertEqual(
            self.client.post(
                reverse("outreach_sms_status", args=[message.pk]), data
            ).status_code,
            403,
        )
        self.assertEqual(
            self.signed_post("outreach_sms_status", data, [message.pk]).status_code, 204
        )
        self.signed_post(
            "outreach_sms_status", {**data, "MessageStatus": "sent"}, [message.pk]
        )
        message.refresh_from_db()
        self.assertEqual(message.delivery_status, "delivered")
        self.assertEqual(message.activity.metadata["delivery_status"], "delivered")
        self.assertEqual(LeadActivity.objects.count(), 1)
        self.assertEqual(
            self.signed_post(
                "outreach_sms_status", {**data, "To": "+16195550000"}, [message.pk]
            ).status_code,
            400,
        )

    def test_callback_can_finish_ambiguous_submission(self):
        message = self.draft("sms")
        with patch(
            "crm.outreach.send_sms",
            side_effect=OutreachError("timeout", uncertain=True),
        ):
            self.send(message)
        data = {
            "MessageSid": "SMone",
            "To": message.recipient,
            "From": message.sender,
            "MessageStatus": "sent",
        }
        self.signed_post("outreach_sms_status", data, [message.pk])
        message.refresh_from_db()
        self.assertEqual(message.status, "sent")
        self.assertEqual(LeadActivity.objects.count(), 1)

    def test_replies_stop_and_duplicate_webhooks(self):
        message = self.draft("sms")
        with patch("crm.outreach.send_sms", return_value=("SMone", "queued")):
            self.send(message)
        reply = {
            "MessageSid": "SMinbound",
            "From": message.recipient,
            "To": message.sender,
            "Body": "STOP",
        }
        self.assertEqual(
            self.signed_post("outreach_sms_inbound", reply).status_code, 200
        )
        self.signed_post("outreach_sms_inbound", reply)
        self.assertEqual(SalesSMSReply.objects.count(), 1)
        self.assertEqual(LeadActivity.objects.count(), 2)
        self.assertTrue(SalesSMSContact.objects.get().opted_out)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "do_not_contact")
        self.assertEqual(
            self.client.get(reverse("lead_detail", args=[self.lead.pk])).status_code,
            200,
        )
        self.signed_post(
            "outreach_sms_inbound", {**reply, "MessageSid": "SMstart", "Body": "START"}
        )
        self.assertFalse(SalesSMSContact.objects.get().opted_out)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, "do_not_contact")

    def test_google_flow_minimum_scope_pkce_and_single_use_state(self):
        response = self.client.post(reverse("outreach_google_connect"))
        query = parse_qs(urlsplit(response.url).query)
        self.assertIn(GMAIL_SCOPE, query["scope"][0])
        self.assertNotIn("readonly", query["scope"][0])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        state = query["state"][0]
        with patch(
            "crm.outreach_views.google_token",
            return_value={
                "scope": GMAIL_SCOPE,
                "access_token": "test-access",
                "refresh_token": "new-refresh",
            },
        ), patch(
            "crm.outreach_views.google_json",
            return_value={
                "email": "erika@aibiz.guru",
                "email_verified": True,
                "hd": "aibiz.guru",
                "sub": "google-123",
            },
        ):
            response = self.client.get(
                reverse("outreach_google_callback"),
                {"state": state, "code": "test-code"},
            )
        self.assertEqual(response.status_code, 302)
        self.mailbox.refresh_from_db()
        self.assertEqual(decrypt_value(self.mailbox.refresh_token), "new-refresh")
        self.assertNotEqual(self.mailbox.refresh_token, "new-refresh")
        self.assertNotIn("sales_google_oauth", self.client.session)
        with patch("crm.outreach_views.google_token") as exchange:
            self.client.get(
                reverse("outreach_google_callback"),
                {"state": state, "code": "test-code"},
            )
        exchange.assert_not_called()

    def test_oauth_rejects_wrong_state_expired_wrong_domain_or_denied_scope(self):
        for mutation in ["state", "expired", "domain", "scope", "unverified"]:
            self.client.post(reverse("outreach_google_connect"))
            session = self.client.session
            state = session["sales_google_oauth"]["state"]
            if mutation == "expired":
                session["sales_google_oauth"]["at"] = time.time() - 700
                session.save()
            with patch(
                "crm.outreach_views.google_token",
                return_value={
                    "scope": GMAIL_SCOPE if mutation != "scope" else "email",
                    "access_token": "access",
                    "refresh_token": "bad-refresh",
                },
            ), patch(
                "crm.outreach_views.google_json",
                return_value={
                    "email": "erika@aibiz.guru",
                    "email_verified": mutation != "unverified",
                    "hd": "evil.example" if mutation == "domain" else "aibiz.guru",
                    "sub": "google-123",
                },
            ):
                self.client.get(
                    reverse("outreach_google_callback"),
                    {
                        "state": "wrong" if mutation == "state" else state,
                        "code": "code",
                    },
                )
            self.mailbox.refresh_from_db()
            self.assertEqual(decrypt_value(self.mailbox.refresh_token), "test-refresh")

    def test_gmail_mime_uses_reviewed_body_actual_sender_and_to_only(self):
        message = self.draft()
        message.body = "Hi Sam,\nAn exact reviewed message."
        with patch(
            "crm.outreach_providers.google_token",
            return_value={"access_token": "access"},
        ), patch(
            "crm.outreach_providers.google_json", return_value={"id": "gmail-id"}
        ) as transport:
            self.assertEqual(
                send_gmail(message, self.mailbox, "Erika"), ("gmail-id", "submitted")
            )
        mime = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(transport.call_args.kwargs["payload"]["raw"])
        )
        self.assertIn(self.mailbox.email, mime["From"])
        self.assertEqual(mime["To"], message.recipient)
        self.assertIsNone(mime["Bcc"])
        self.assertEqual(mime.get_content().rstrip("\n"), message.body)

    def test_connection_page_never_exposes_tokens_and_phone_validation(self):
        page = self.client.get(reverse("outreach_connections"))
        self.assertContains(page, self.mailbox.email)
        self.assertNotContains(page, self.mailbox.refresh_token)
        self.assertNotContains(page, "test-secret")
        self.assertEqual(phone_number("(619) 555-0199"), "+16195550199")
        for bad in ["123", "+1abc1234567", "6195550199 ext 123"]:
            with self.assertRaises(OutreachError):
                phone_number(bad)
