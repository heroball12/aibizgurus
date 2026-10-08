import json
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from core.models import DemoCRMLead, DemoRepAccess, DemoSession
from core.experience import tools
from crm.models import Lead


class IPadExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_center", publish=True, stdout=StringIO())
        cls.rep = User.objects.create_user(username="ipad-rep", role="employee")
        cls.customer = User.objects.create_user(username="ipad-client", role="client")

    def post(self, name, data, client=None):
        return (client or self.client).post(reverse("experience_ipad:" + name), json.dumps(data), content_type="application/json")

    def start(self):
        self.client.force_login(self.rep)
        response = self.post("session", {})
        self.assertEqual(response.status_code, 201)
        return DemoSession.objects.get(pk=response.json()["id"])

    def test_app_requires_employee_but_public_website_remains_available(self):
        self.assertEqual(self.client.get(reverse("experience_ipad:home")).status_code, 302)
        self.assertEqual(self.client.get(reverse("experience_home")).status_code, 200)
        for name in ("session", "turn", "action", "finance", "service", "transcribe", "speech"):
            response = self.post(name, {})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "signin_required")
            self.assertIn("no-store", response["Cache-Control"])
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse("experience_ipad:home")), "Employee access required", status_code=403)

    def test_dedicated_login_returns_to_app_and_never_accepts_external_next(self):
        self.rep.set_password("test-only-password")
        self.rep.save()
        login = reverse("experience_ipad:login")
        self.assertContains(self.client.get(login), "Your showroom")
        response = self.client.post(login, {"username": self.rep.username, "password": "test-only-password", "next": "https://example.com/"})
        self.assertRedirects(response, reverse("experience_ipad:home"))

    def test_private_page_uses_private_endpoints_and_scoped_layout(self):
        self.client.force_login(self.rep)
        response = self.client.get(reverse("experience_ipad:home"))
        self.assertContains(response, "experience-ipad.css")
        self.assertNotContains(response, 'id="teamNotificationCenter"')
        config = response.context["demo_config"]
        self.assertTrue(config["ipadApp"])
        for key in ("sessionUrl", "turnUrl", "voiceUrl", "speechUrl", "crmUrl", "financeUrl", "serviceUrl", "actionUrl"):
            self.assertTrue(config[key].startswith("/demo/automotive/ipad/"))
        public = self.client.get(reverse("experience_home"))
        self.assertNotContains(public, "experience-ipad.css")
        self.assertFalse(public.context["demo_config"]["ipadApp"])

    def test_private_session_revocation_applies_to_public_endpoints_too(self):
        session = self.start()
        self.assertEqual(session.source, "ipad")
        self.assertEqual(self.post("session", {"resume": str(session.pk)}).status_code, 200)
        DemoRepAccess.objects.create(user=self.rep, enabled=False)
        self.assertEqual(self.post("session", {"resume": str(session.pk)}).status_code, 403)
        public = self.client.post(reverse("experience_session"), json.dumps({"resume": str(session.pk)}), content_type="application/json")
        self.assertEqual(public.status_code, 404)
        self.assertEqual(self.client.get(reverse("experience_crm"), {"session": session.pk}).status_code, 404)

    def test_public_and_other_browser_sessions_cannot_enter_private_crm(self):
        session = self.start()
        other = Client(); other.force_login(self.rep)
        self.assertEqual(self.post("session", {"resume": str(session.pk)}, client=other).status_code, 404)
        public = self.client.post(reverse("experience_session"), "{}", content_type="application/json").json()
        self.assertEqual(self.post("session", {"resume": public["id"]}).status_code, 404)

    def test_customer_handoff_crm_edit_return_and_reset_use_same_prospect(self):
        session = self.start()
        tools.execute(session, "update_customer", {"name": "Jamie Sample", "phone": "202-555-0148", "email": "jamie@example.com", "interest": "SUV"})
        tools.sync_crm(session)
        session.save()
        url = reverse("experience_ipad:crm") + "?session=" + str(session.pk)
        response = self.client.post(url, {"action": "signin"})
        self.assertRedirects(response, url)
        self.assertContains(self.client.get(url), "Jamie Sample")
        self.assertEqual(self.client.get(url).context["state_url"], reverse("experience_ipad:crm_state") + "?session=" + str(session.pk))
        self.client.post(url, {"action": "update", "stage": "follow_up", "notes": "Sample follow-up", "assigned_to": "Elena Rivera · BDC"})
        self.assertEqual(DemoCRMLead.objects.get(session=session).staff_notes, "Sample follow-up")
        resumed = self.post("session", {"resume": str(session.pk)}).json()
        self.assertEqual(resumed["state"]["customer"]["name"], "Jamie Sample")
        self.assertEqual(self.post("action", {"session": str(session.pk), "action": "reset"}).status_code, 200)
        self.assertFalse(DemoCRMLead.objects.filter(session=session).exists())
        self.assertEqual(Lead.objects.count(), 0)

    def test_csrf_and_signout_preserve_real_auth_boundary(self):
        c = Client(enforce_csrf_checks=True); c.force_login(self.rep)
        self.assertEqual(self.post("session", {}, client=c).status_code, 403)
        self.assertEqual(c.post(reverse("experience_ipad:signout")).status_code, 403)
        session = self.start()
        self.client.post(reverse("experience_ipad:signout"))
        self.assertEqual(self.post("session", {"resume": str(session.pk)}).status_code, 403)
