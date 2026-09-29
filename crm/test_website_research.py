import socket
import time
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse

from .models import Lead, LeadStaging, LeadGenerationBatch
from .lead_finder import convert_staging_to_crm_lead
from .public_site import SiteError, safe_url, public_address, fetch_page
from .website_research import PageFacts, inspect_pages, research_website

PAGE = """<html><head><title>Aster Salon</title><meta name="description" content="Haircuts, color and event styling.">
<script src="https://www.chatbase.co/embed.min.js"></script>
<script type="application/ld+json">{"@type":"LocalBusiness","address":{"streetAddress":"123 Main St","addressLocality":"San Diego"},"openingHours":["Mo-Fr 09:00-17:00"]}</script>
</head><body><h1>Hair &amp; color</h1><a href="mailto:hello@aster.example">Email</a><a href="tel:+16195550199">Call</a>
<a href="https://calendly.com/aster">Book an appointment</a><a href="/cart">View cart</a><a href="/about">About us</a><a href="/contact">Contact us</a></body></html>"""


class WebsiteAnalysisTests(SimpleTestCase):
    def test_evidence_contacts_and_business_details(self):
        page = PageFacts("https://aster.example/")
        page.feed(PAGE)
        details, signals = inspect_pages([page])
        self.assertEqual(signals["chat"]["status"], "ai_detected")
        self.assertEqual(signals["booking"]["status"], "detected")
        self.assertEqual(signals["checkout"]["status"], "detected")
        self.assertEqual(details["emails"], ["hello@aster.example"])
        self.assertEqual(details["address"], "123 Main St, San Diego")
        self.assertIn("Hair & color", details["headings"])
        self.assertEqual(signals["chat"]["evidence"][0]["page"], page.url)

    def test_mentions_of_ai_tools_do_not_prove_integration_or_missing_features(self):
        page = PageFacts("https://aster.example/")
        page.feed(
            '<h1>We wrote about Chatbase and AI chat</h1><p>https://chatbase.co/embed.min.js</p><a href="/books">Book collection</a>'
        )
        _, signals = inspect_pages([page])
        self.assertEqual(signals["chat"]["status"], "not_observed")
        self.assertEqual(signals["booking"]["status"], "not_observed")
        self.assertEqual(signals["checkout"]["status"], "not_observed")

    def test_generic_chat_is_not_misrepresented_as_ai(self):
        page = PageFacts("https://aster.example/")
        page.feed('<script src="https://widget.intercom.io/widget/abc"></script>')
        _, signals = inspect_pages([page])
        self.assertEqual(signals["chat"]["status"], "chat_detected")
        page = PageFacts("https://aster.example/")
        page.feed(
            '<script src="https://chatbase.co.attacker.example/embed.min.js"></script>'
        )
        _, signals = inspect_pages([page])
        self.assertEqual(signals["chat"]["status"], "not_observed")

    def test_bounded_scan_respects_robots_and_only_follows_about_contact(self):
        def fetch(url, **kwargs):
            return (
                (url, "User-agent: *\nDisallow: /contact")
                if url.endswith("/robots.txt")
                else (url, PAGE)
            )

        with patch("crm.website_research.fetch_page", side_effect=fetch) as request:
            report = research_website("https://aster.example/")
        self.assertEqual(
            report["pages"], ["https://aster.example/", "https://aster.example/about"]
        )
        self.assertEqual(request.call_count, 3)
        self.assertTrue(report["warnings"])
        self.assertIn("not a live browser", report["limitation"])

    def test_robots_denial_and_failures_stop_scanning(self):
        with patch(
            "crm.website_research.fetch_page",
            return_value=(
                "https://aster.example/robots.txt",
                "User-agent: *\nDisallow: /",
            ),
        ) as fetch:
            with self.assertRaises(SiteError):
                research_website("https://aster.example/")
        self.assertEqual(fetch.call_count, 1)
        with patch(
            "crm.website_research.fetch_page",
            side_effect=SiteError("Denied", status=403),
        ):
            with self.assertRaises(SiteError):
                research_website("https://aster.example/")

    def test_private_mixed_dns_and_encoded_urls_rejected(self):
        for bad in [
            "file:///etc/passwd",
            "http://user:password@example.com/",
            "http://localhost/",
            "https://example.com:8443/",
            "http://example.com/\nHeader: true",
        ]:
            self.assertEqual(safe_url(bad), "")
        for ip in [
            "127.0.0.1",
            "10.0.0.5",
            "169.254.169.254",
            "::1",
            "::ffff:127.0.0.1",
            "224.0.0.1",
            "0.0.0.0",
        ]:
            with patch(
                "socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))],
            ):
                with self.assertRaises(SiteError):
                    public_address("rebind.example", 80)
        with patch(
            "socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
            ],
        ):
            with self.assertRaises(SiteError):
                public_address("mixed.example", 80)

    def test_public_fetch_pins_dns_and_revalidates_redirects(self):
        response = MagicMock()
        response.status = 302
        response.getheader.return_value = "http://127.0.0.1/private"
        conn = MagicMock()
        conn.getresponse.return_value = response
        with patch(
            "crm.public_site.public_address",
            side_effect=["8.8.8.8", SiteError("private")],
        ) as resolve, patch(
            "crm.public_site.http.client.HTTPConnection", return_value=conn
        ), patch(
            "crm.public_site.socket.create_connection"
        ) as connect:
            with self.assertRaises(SiteError):
                fetch_page("http://public.example/", deadline=time.monotonic() + 10)
        self.assertEqual(resolve.call_count, 2)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[0], ("8.8.8.8", 80))
        self.assertEqual(
            conn.request.call_args.kwargs["headers"]["Host"], "public.example"
        )

    def test_size_limit_and_non_html_are_enforced(self):
        response = MagicMock()
        response.status = 200
        response.getheader.side_effect = lambda key, default="": {
            "Content-Type": "application/pdf",
            "Content-Encoding": "identity",
        }.get(key, default)
        conn = MagicMock()
        conn.getresponse.return_value = response
        with patch("crm.public_site.public_address", return_value="8.8.8.8"), patch(
            "crm.public_site.http.client.HTTPConnection", return_value=conn
        ), patch("crm.public_site.socket.create_connection"):
            with self.assertRaises(SiteError):
                fetch_page("http://public.example/", deadline=time.monotonic() + 10)
            response.getheader.side_effect = lambda key, default="": {
                "Content-Type": "text/html",
                "Content-Encoding": "identity",
            }.get(key, default)
            response.read1.return_value = b"x" * 200000
            with self.assertRaises(SiteError):
                fetch_page("http://public.example/", deadline=time.monotonic() + 10)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class WebsiteResearchViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="researcher", role="employee"
        )
        self.other = get_user_model().objects.create_user(
            username="other", role="employee"
        )
        self.batch = LeadGenerationBatch.objects.create(
            employee=self.user, industry="Salon", status="completed"
        )
        self.row = LeadStaging.objects.create(
            batch=self.batch,
            business_name="Aster",
            industry="Salon",
            website="https://aster.example/",
            created_by=self.user,
        )
        self.client.force_login(self.user)
        page = PageFacts(self.row.website)
        page.feed(PAGE)
        details, findings = inspect_pages([page])
        self.report = {
            "website": self.row.website,
            "checked_at": "2026-09-29T10:00:00+00:00",
            "details": details,
            "findings": findings,
            "pages": [self.row.website],
            "warnings": [],
            "limitation": "Public code only.",
        }

    def test_button_saved_report_cache_and_pipeline_transfer(self):
        response = self.client.get(
            reverse("lead_generation_batch_detail", args=[self.batch.pk])
        )
        self.assertContains(response, "Dig deeper")
        with patch(
            "crm.research_views.research_website", return_value=self.report
        ) as scan:
            response = self.client.post(
                reverse("prospect_research", args=[self.row.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.client.post(reverse("prospect_research", args=[self.row.pk]))
        scan.assert_called_once()
        self.row.refresh_from_db()
        self.assertEqual(self.row.website_review, self.report)
        lead = convert_staging_to_crm_lead(
            self.row, employee=self.user, contacted=False
        )
        self.assertEqual(lead.website_review, self.report)
        self.assertEqual(lead.status, "new")
        self.assertIsNone(lead.last_contact_at)
        self.assertEqual(
            self.client.get(reverse("lead_research", args=[lead.pk])).status_code, 200
        )

    def test_access_cache_isolation_and_error_preserves_old_report(self):
        self.client.force_login(self.other)
        with patch("crm.research_views.research_website") as scan:
            self.assertEqual(
                self.client.post(
                    reverse("prospect_research", args=[self.row.pk])
                ).status_code,
                404,
            )
        scan.assert_not_called()
        self.client.force_login(self.user)
        self.row.website_review = self.report
        self.row.save()
        with patch(
            "crm.research_views.research_website", side_effect=SiteError("blocked")
        ):
            response = self.client.post(
                reverse("prospect_research", args=[self.row.pk]), {"refresh": "1"}
            )
        self.assertEqual(response.status_code, 422)
        self.row.refresh_from_db()
        self.assertEqual(self.row.website_review, self.report)

    def test_report_escapes_scraped_markup_and_rechecks_website_after_fetch(self):
        report = {
            **self.report,
            "details": {**self.report["details"], "title": "<script>alert(1)</script>"},
        }
        with patch("crm.research_views.research_website", return_value=report):
            response = self.client.post(
                reverse("prospect_research", args=[self.row.pk])
            )
        self.assertNotIn("<script>", response.json()["html"])
        self.assertIn("&lt;script&gt;", response.json()["html"])
        self.row.website = "https://new.example/"
        self.row.save()
        self.assertEqual(
            self.client.get(
                reverse("prospect_research", args=[self.row.pk])
            ).status_code,
            404,
        )

    def test_read_only_get_never_scans(self):
        with patch("crm.research_views.research_website") as scan:
            self.assertEqual(
                self.client.get(
                    reverse("prospect_research", args=[self.row.pk])
                ).status_code,
                404,
            )
        scan.assert_not_called()


class CustomAssistantTests(SimpleTestCase):
    def test_custom_ai_link_is_reported_without_claiming_live_verification(self):
        page = PageFacts("https://example.com/")
        page.feed(
            '<a href="/ai/concierge/" aria-label="Open AI growth concierge">Meet your AI employee</a>'
        )
        _, signals = inspect_pages([page])
        self.assertEqual(signals["chat"]["status"], "chat_detected")
        self.assertIn("unconfirmed", signals["chat"]["evidence"][0]["detail"])
