import json
from unittest.mock import MagicMock, patch
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from .business_status import (
    listing_closure,
    verify_business,
    website_closure,
    contact_blocked,
)
from .lead_finder import OpenStreetMapProvider, convert_staging_to_crm_lead
from .models import Lead, LeadStaging, LeadGenerationBatch
from .public_site import SiteError
from .website_research import PageFacts


class BusinessEvidenceTests(SimpleTestCase):
    def test_lifecycle_flags_but_not_old_building_features_or_daily_closures(self):
        for tags in [
            {"disused:shop": "hairdresser"},
            {"shop": "hairdresser", "disused:shop": "hairdresser"},
            {"closed": "yes"},
            {"shop": "vacant"},
            {"end_date": "2020-01-01"},
            {"opening_hours": "closed"},
        ]:
            self.assertTrue(listing_closure(tags), tags)
        for tags in [
            {"shop": "hairdresser", "disused:shop": "convenience"},
            {"disused:parking": "yes"},
            {"opening_hours": "Mo-Fr 09:00-17:00; Su off"},
            {"opening_hours:covid19": "closed"},
            {"end_date": "2099-01-01"},
        ]:
            self.assertFalse(listing_closure(tags), tags)

    def test_prominent_closure_not_normal_business_hours(self):
        for html, expected in [
            ("<h1>We have permanently closed</h1>", True),
            ("<title>Aster — permanently closed</title>", True),
            ("<h1>Temporarily closed</h1>", True),
            ("<h1>We are closed on Sundays</h1>", False),
            ("<p>An article about another shop that is permanently closed.</p>", False),
        ]:
            page = PageFacts("https://example.com")
            page.feed(html)
            self.assertEqual(bool(website_closure(page)), expected)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    LEAD_FINDER_ENABLE_PUBLIC_HTTP=True,
)
class BusinessVerificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="status-rep", role="employee"
        )
        self.batch = LeadGenerationBatch.objects.create(
            employee=self.user, industry="Salon", status="completed"
        )
        self.row = LeadStaging.objects.create(
            batch=self.batch,
            business_name="Aster",
            industry="Salon",
            website="https://aster.example/",
            source_url="https://www.openstreetmap.org/node/123",
            created_by=self.user,
        )
        self.client.force_login(self.user)

    def response(self, tags):
        result = MagicMock()
        result.read.return_value = json.dumps({"elements": [{"tags": tags}]}).encode()
        return result

    def test_current_listing_closed_is_flagged_even_when_website_fails(self):
        with patch("crm.business_status.request.urlopen") as request, patch(
            "crm.website_research.research_website", side_effect=SiteError("offline")
        ):
            request.return_value.__enter__.return_value = self.response(
                {"name": "Aster", "disused:shop": "hairdresser"}
            )
            verification, report = verify_business(self.row)
        self.assertEqual(verification["status"], "not_operating")
        self.assertIsNone(report)
        self.assertIn("does not prove", verification["warnings"][0])

    def test_healthy_site_is_not_proof_of_open_and_changed_listing_needs_review(self):
        for name, expected in [
            ("Aster", "unverified"),
            ("Different Business", "needs_review"),
        ]:
            with patch("crm.business_status.request.urlopen") as request, patch(
                "crm.website_research.research_website",
                return_value={"pages": [self.row.website]},
            ):
                request.return_value.__enter__.return_value = self.response(
                    {"name": name, "shop": "hairdresser"}
                )
                verification, _ = verify_business(self.row)
            self.assertEqual(verification["status"], expected)

    def test_malicious_source_url_is_never_fetched(self):
        self.row.source_url = "http://169.254.169.254/metadata"
        self.row.website = ""
        with patch("crm.business_status.request.urlopen") as request:
            result, _ = verify_business(self.row)
        request.assert_not_called()
        self.assertEqual(result["status"], "unverified")

    def test_closed_status_blocks_pipeline_until_employee_verifies_open(self):
        result = {
            "status": "not_operating",
            "label": "Listing reports not operating",
            "evidence": [],
        }
        with patch("crm.research_views.verify_business", return_value=(result, None)):
            self.assertEqual(
                self.client.post(
                    reverse("prospect_verify", args=[self.row.pk])
                ).status_code,
                200,
            )
        self.row.refresh_from_db()
        with self.assertRaises(ValueError):
            convert_staging_to_crm_lead(self.row, employee=self.user, contacted=False)
        response = self.client.post(
            reverse("prospect_verify", args=[self.row.pk]),
            {
                "action": "confirm",
                "status": "confirmed_open",
                "note": "Called the owner today; business has reopened.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.business_verification["confirmed_by"], "status-rep")
        lead = convert_staging_to_crm_lead(
            self.row, employee=self.user, contacted=False
        )
        self.assertEqual(lead.business_verification["status"], "confirmed_open")

    def test_manual_outcome_requires_explanation_and_does_not_clear_dnc(self):
        self.assertEqual(
            self.client.post(
                reverse("prospect_verify", args=[self.row.pk]),
                {"action": "confirm", "status": "confirmed_open", "note": "yes"},
            ).status_code,
            400,
        )
        lead = Lead.objects.create(
            business_name="Aster", assigned_to=self.user, status="do_not_contact"
        )
        self.client.post(
            reverse("lead_verify", args=[lead.pk]),
            {
                "action": "confirm",
                "status": "confirmed_open",
                "note": "Owner confirmed the business is operating.",
            },
        )
        lead.refresh_from_db()
        self.assertEqual(lead.status, "do_not_contact")
        lead.status = "new"
        lead.business_verification = {"status": "needs_review"}
        lead.save()
        self.assertTrue(contact_blocked(lead))

    def test_new_search_excludes_lifecycle_closures(self):
        from django.core.cache import cache

        cache.clear()
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 11,
                        "tags": {
                            "name": "Closed Cafe",
                            "phone": "6195550100",
                            "disused:amenity": "cafe",
                        },
                    },
                    {
                        "type": "node",
                        "id": 12,
                        "tags": {
                            "name": "Current Listing",
                            "phone": "6195550101",
                            "amenity": "cafe",
                        },
                    },
                ]
            }
        ).encode()
        with patch("crm.lead_finder.request.urlopen") as request:
            request.return_value.__enter__.return_value = response
            provider = OpenStreetMapProvider()
            rows = provider.search(
                industry="restaurant", location="San Diego, CA", limit=5
            )
        self.assertEqual([r.business_name for r in rows], ["Current Listing"])
        self.assertEqual(provider.summary["closed_excluded"], 1)
        self.assertEqual(rows[0].business_verification["status"], "unverified")


class VerificationMergeTests(SimpleTestCase):
    def test_inconclusive_recheck_keeps_prior_closure_and_direct_confirmation(self):
        from .business_status import merge_verification

        for state in [
            "confirmed_closed",
            "confirmed_open",
            "not_operating",
            "needs_review",
            "temporarily_closed",
        ]:
            prior = {"status": state, "evidence": [{"detail": "Earlier evidence"}]}
            result = merge_verification(
                prior, {"status": "unverified", "checked_at": "today", "evidence": []}
            )
            self.assertEqual(result["status"], state)
            self.assertEqual(result["rechecked_at"], "today")
            self.assertTrue(result["warnings"])
