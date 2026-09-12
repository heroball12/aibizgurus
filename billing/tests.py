from unittest.mock import patch
from types import SimpleNamespace

import stripe
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from clients.models import ClientAccount, AIInstance
from .models import BillingCustomer, BillingEvent


@override_settings(STRIPE_SECRET_KEY="sk_test_unit_only", STRIPE_WEBHOOK_SECRET="whsec_unit_only", STRIPE_PRICE_STARTER="price_starter", STRIPE_PRICE_GROWTH="price_growth", STRIPE_PRICE_PRO="price_pro", STRIPE_SETUP_PRICE_STARTER="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BillingLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="billing-client",password="UnitOnly-Password2026!")
        self.account = ClientAccount.objects.create(user=self.user,business_name="Billing Sample",contact_email="sample@example.test")
        self.ai = AIInstance.objects.create(client=self.account,name="Billing Assistant",status="draft")
        self.subscription = {"id":"sub_sample","customer":"cus_sample","status":"active","metadata":{"client_id":str(self.account.pk),"plan":"growth"},"items":{"data":[{"price":{"id":"price_growth"},"current_period_end":1900000000}]}}

    def webhook(self, kind, obj, *, event_id="evt_sample", subscription=None):
        event={"id":event_id,"type":kind,"data":{"object":obj}}
        with patch("billing.views.stripe.Webhook.construct_event",return_value=event), patch("billing.views.stripe.Subscription.retrieve",return_value=subscription or self.subscription) as retrieve:
            response = self.client.post(reverse("stripe_webhook"),data=b"{}",content_type="application/json")
        return response, retrieve

    def test_checkout_completion_persists_customer_plan_and_activation(self):
        response,_=self.webhook("checkout.session.completed",{"mode":"subscription","client_reference_id":str(self.account.pk),"subscription":"sub_sample","customer":"cus_sample","payment_status":"paid"})
        self.assertEqual(response.status_code,200)
        self.account.refresh_from_db(); self.ai.refresh_from_db()
        self.assertEqual(self.account.activation_status,"active")
        self.assertEqual(self.account.plan,"growth")
        self.assertEqual(self.ai.status,"active")
        customer=BillingCustomer.objects.get(client=self.account)
        self.assertEqual(customer.stripe_customer_id,"cus_sample")
        self.assertEqual(customer.stripe_subscription_id,"sub_sample")
        self.assertIsNotNone(customer.current_period_end)

    def test_unpaid_checkout_does_not_activate_incomplete_subscription(self):
        self.webhook("checkout.session.completed",{"mode":"subscription","client_reference_id":str(self.account.pk),"subscription":"sub_sample","payment_status":"unpaid"},subscription={**self.subscription,"status":"incomplete"})
        self.account.refresh_from_db()
        self.assertEqual(self.account.activation_status,"pending_payment")

    def test_retries_are_idempotent_and_delayed_events_use_current_state(self):
        self.webhook("customer.subscription.created",self.subscription)
        response,retrieve=self.webhook("customer.subscription.created",self.subscription)
        self.assertEqual(response.status_code,200); retrieve.assert_not_called()
        self.assertEqual(BillingEvent.objects.count(),1)
        canceled={**self.subscription,"status":"canceled"}
        self.webhook("customer.subscription.deleted",canceled,event_id="evt_cancel",subscription=canceled)
        self.webhook("customer.subscription.updated",self.subscription,event_id="evt_delayed",subscription=canceled)
        self.account.refresh_from_db();self.ai.refresh_from_db()
        self.assertEqual(self.account.activation_status,"cancelled")
        self.assertEqual(self.ai.status,"draft")

    def test_failed_invoice_pauses_and_paid_invoice_restores(self):
        self.webhook("customer.subscription.created",self.subscription)
        invoice={"customer":"cus_sample","parent":{"subscription_details":{"subscription":"sub_sample"}}}
        self.webhook("invoice.payment_failed",invoice,event_id="evt_failure",subscription={**self.subscription,"status":"past_due"})
        self.account.refresh_from_db();self.ai.refresh_from_db()
        self.assertEqual(self.account.activation_status,"paused")
        self.assertEqual(self.ai.status,"paused")
        self.webhook("invoice.paid",invoice,event_id="evt_paid")
        self.account.refresh_from_db();self.assertEqual(self.account.activation_status,"active")

    def test_stripe_failure_returns_retryable_response_without_receipt(self):
        event={"id":"evt_network","type":"customer.subscription.updated","data":{"object":self.subscription}}
        with patch("billing.views.stripe.Webhook.construct_event",return_value=event), patch("billing.views.stripe.Subscription.retrieve",side_effect=stripe.error.APIConnectionError("test failure")):
            response=self.client.post(reverse("stripe_webhook"),data=b"{}",content_type="application/json")
        self.assertEqual(response.status_code,503)
        self.assertFalse(BillingEvent.objects.exists())

    @override_settings(STRIPE_WEBHOOK_SECRET="")
    def test_unconfigured_webhook_fails_closed(self):
        response=self.client.post(reverse("stripe_webhook"),data=b"{}",content_type="application/json")
        self.assertEqual(response.status_code,503)
        self.assertFalse(BillingEvent.objects.exists())

    @patch("billing.views.stripe.checkout.Session.create")
    def test_checkout_is_post_only_and_includes_client_metadata(self, create):
        class Session(dict):
            url="https://checkout.stripe.com/c/pay/test-only"
        create.return_value=Session(status="open")
        self.client.force_login(self.user)
        url=reverse("create_checkout_session",args=["starter"])
        self.assertEqual(self.client.get(url).status_code,405)
        response=self.client.post(url)
        self.assertEqual(response.status_code,302)
        kwargs=create.call_args.kwargs
        self.assertEqual(kwargs["subscription_data"]["metadata"],{"client_id":str(self.account.pk),"plan":"starter"})
        self.assertEqual(kwargs["line_items"],[{"price":"price_starter","quantity":1}])
        self.assertIn("{CHECKOUT_SESSION_ID}",kwargs["success_url"])
        nonce=kwargs["idempotency_key"]
        self.client.post(url)
        self.assertEqual(create.call_args.kwargs["idempotency_key"],nonce)

    @patch("billing.views.stripe.checkout.Session.create")
    def test_existing_subscription_prevents_duplicate_checkout(self,create):
        BillingCustomer.objects.create(client=self.account,stripe_subscription_id="sub_sample",status="past_due")
        self.client.force_login(self.user)
        self.client.post(reverse("create_checkout_session",args=["starter"]))
        create.assert_not_called()

    @patch("billing.views.stripe.checkout.Session.retrieve")
    def test_success_url_cannot_claim_another_customers_payment(self,retrieve):
        retrieve.return_value={"client_reference_id":"999999","mode":"subscription","subscription":"sub_other"}
        self.client.force_login(self.user)
        self.client.get(reverse("payment_success")+"?session_id=cs_other")
        self.account.refresh_from_db();self.assertEqual(self.account.activation_status,"demo")

    @patch("billing.views.stripe.billing_portal.Session.create")
    def test_customer_portal_uses_the_logged_in_clients_customer(self,create):
        create.return_value=SimpleNamespace(url="https://billing.stripe.com/p/session/test-only")
        BillingCustomer.objects.create(client=self.account,stripe_customer_id="cus_sample")
        self.client.force_login(self.user)
        self.client.post(reverse("customer_portal"))
        self.assertEqual(create.call_args.kwargs["customer"],"cus_sample")

    @patch("billing.views.stripe.checkout.Session.list")
    def test_legacy_subscription_links_using_old_checkout_reference(self,sessions):
        sessions.return_value={"data":[{"status":"complete","client_reference_id":str(self.account.pk),"customer":"cus_sample"}]}
        legacy={**self.subscription,"metadata":{}}
        response,_=self.webhook("customer.subscription.updated",legacy,subscription=legacy)
        self.assertEqual(response.status_code,200)
        self.assertEqual(BillingCustomer.objects.get().stripe_subscription_id,"sub_sample")
        sessions.assert_called_once()
