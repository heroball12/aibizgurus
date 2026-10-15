import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse

from .chain_detection import major_chain_name
from .lead_finder import create_generation_batch, generate_leads_for_batch


class ChainDetectionTests(SimpleTestCase):
    def test_recognizes_exact_brands_branch_labels_metadata_and_domains(self):
        for name, website, tags, expected in [
            ("McDonald’s #123", "", {}, "McDonald's"),
            ("Bruegger's Bagels – Miami", "", {}, "Bruegger's Bagels"),
            ("Local shop", "", {"brand": "Starbucks"}, "Starbucks"),
            ("Jane Smith", "https://agents.allstate.com/jane", {}, "Allstate"),
            ("Branch", "", {"operator": "Great Clips"}, "Great Clips"),
            ("Jane Smith - State Farm Insurance Agent", "", {}, "State Farm"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(major_chain_name(name, website, tags), expected)

    def test_does_not_guess_from_similar_names_unknown_brands_or_shared_hosts(self):
        for name, website, tags in [
            ("Target Marketing", "https://targetmarketing.example", {}),
            ("Subway Auto Repair", "https://example.com/subway.com", {}),
            ("Independent Cafe", "https://starbucks.com.example.org", {}),
            ("Cedar Cafe", "https://square.site/cedar", {"brand": "Cedar Cafe", "brand:wikidata": "Q123"}),
            ("Temecula Toyota", "https://example.com", {"brand": "Toyota"}),
            ("Coffee", "http://[invalid", {}),
        ]:
            with self.subTest(name=name):
                self.assertEqual(major_chain_name(name, website, tags), "")


@override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=True, CELERY_BROKER_URL="")
class ChainSearchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rep = get_user_model().objects.create_user(username="chain-rep", role="employee")
        self.client.force_login(self.rep)

    def batch(self, exclude=True, quantity=5):
        return create_generation_batch(employee=self.rep, industry="Restaurant", location="Miami, FL",
                                       quantity=quantity, exclude_major_chains=exclude)

    @patch("crm.lead_finder.request.urlopen")
    def test_filters_before_limit_and_cached_data_can_include_chains_on_request(self, urlopen):
        tags = [{"name": "Brand location", "brand": "Starbucks"},
                {"name": "Bruegger's Bagels"}, {"name": "Zoe's Independent Cafe"}]
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({"elements": [
            {"type": "node", "id": i + 1, "tags": {**t, "phone": f"305555010{i}"}}
            for i, t in enumerate(tags)
        ]}).encode()
        batch = generate_leads_for_batch(self.batch(quantity=1).pk)
        self.assertEqual(batch.staged_leads.get().business_name, "Zoe's Independent Cafe")
        self.assertEqual(batch.provider_summary["chains_excluded"], 2)
        unfiltered = generate_leads_for_batch(self.batch(False).pk)
        self.assertEqual(unfiltered.quantity_generated, 2)  # Independent already saved.
        self.assertEqual(unfiltered.provider_summary["chains_excluded"], 0)
        self.assertTrue(unfiltered.provider_summary["directory"]["cached"])
        self.assertEqual(urlopen.call_count, 1)

    def test_filter_is_default_and_post_and_retry_preserve_choice(self):
        page = self.client.get(reverse("lead_finder"))
        self.assertTrue(page.context["form"]["exclude_major_chains"].value())
        for exclude in (True, False):
            data = {"industry": "Restaurant", "state": "FL", "city": "Miami", "quantity": "5"}
            if exclude:
                data["exclude_major_chains"] = "on"
            self.client.post(reverse("lead_finder"), data)
            batch = self.rep.lead_generation_batches.latest("pk")
            self.assertEqual(batch.exclude_major_chains, exclude)
            detail = self.client.get(reverse("lead_generation_batch_detail", args=[batch.pk]))
            retry = self.client.get(reverse("lead_finder") + "?" + detail.context["retry_query"])
            self.assertEqual(retry.context["form"]["exclude_major_chains"].value(), exclude)
        self.assertEqual(self.rep.lead_generation_batches.count(), 2)
        self.assertEqual(self.batch(False).pk, batch.pk)  # Same settings reuse active search.

    def test_all_chain_results_explain_empty_search(self):
        from .lead_finder import DirectoryLead
        provider = MagicMock()
        provider.name, provider.summary = "fixture", {}
        provider.search.return_value = [DirectoryLead("McDonald's", "3055550100", "Restaurant")]
        batch = generate_leads_for_batch(self.batch().pk, providers=[provider])
        self.assertEqual(batch.status, "completed")
        self.assertEqual(batch.quantity_generated, 0)
        self.assertIn("Excluded 1 major-chain", batch.status_message)
        self.assertIn("turn off Hide major chains", batch.status_message)
        self.assertEqual(batch.duplicates_removed, 0)
