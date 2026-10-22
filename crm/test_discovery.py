from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse

from . import zoominfo_api as api
from .discovery import finder_url, public_to_zoominfo
from .models import Lead, LeadGenerationBatch, ZoomInfoSearch
from .zoominfo_forms import SearchForm


class DiscoveryContractTests(SimpleTestCase):
    def test_company_search_broadens_geography_without_unsupported_city_field(self):
        form = SearchForm({"industry": "insurance OR insurance brokers", "state": "FL", "zip_code": "33101", "radius": "50", "page_size": "100"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.criteria(), {"industryKeywords": "insurance OR insurance brokers", "country": "United States", "state": "Florida", "zipCode": "33101", "zipCodeRadiusMiles": 50, "excludeDefunctCompanies": True})
        self.assertEqual(form.snapshot()["page_size"], 100)
        self.assertEqual(form.snapshot()["sort_order"], "name")
        self.assertNotIn("page_size", form.criteria())
        state = SearchForm({"industry": "insurance", "state": "FL"})
        nationwide = SearchForm({"industry": "insurance"})
        self.assertTrue(state.is_valid()); self.assertTrue(nationwide.is_valid())
        self.assertNotIn("zipCode", state.criteria())
        self.assertNotIn("state", nationwide.criteria())

    def test_contact_availability_uses_documented_required_fields(self):
        form = SearchForm({"company_id": "2001", "job_title": "Owner OR President", "contact_details": "email,directPhone", "sort_order": "-contactAccuracyScore"}, kind="people")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.criteria()["requiredFields"], "email,directPhone")
        self.assertEqual(form.criteria()["locationSearchType"], "HQ")
        for data in ({"state": "FL", "page_size": "1000"}, {"state": "FL", "radius": "50"}, {"state": "INVALID"}, {"state": "FL", "sort_order": "arbitrary"}):
            self.assertFalse(SearchForm(data).is_valid())

    @patch("crm.zoominfo_api.call")
    def test_100_match_pages_and_continuation_use_same_size(self, call):
        call.return_value = {"data": [{"id": str(n), "attributes": {"name": "Example Company"}} for n in range(1, 101)], "meta": {"totalResults": 201}}
        rows, total, more = api.search("companies", {"state": "Florida"}, 2, page_size=100, sort="name")
        self.assertEqual((len(rows), total, more), (100, 201, True))
        self.assertEqual(call.call_args.kwargs["params"], {"page[number]": 2, "page[size]": 100, "sort": "name"})
        api.search("companies", {"state": "Florida"}, 3, page_size=100)
        self.assertFalse(api.search("companies", {}, 3, page_size=100)[2])
        self.assertEqual(call.call_count, 3)  # Only the three explicit page requests.
        with self.assertRaises(ValueError):
            api.search("people", {}, page_size=101)
        with self.assertRaises(ValueError):
            api.search("people", {}, sort="-revenue")
        self.assertEqual(call.call_count, 3)

    def test_public_handoff_explains_statewide_search_and_preserves_chain_choice(self):
        batch = LeadGenerationBatch(industry="Insurance", location="Miami, FL", exclude_major_chains=False)
        handoff = public_to_zoominfo(batch)
        self.assertEqual(handoff["area"], "Florida")
        query = parse_qs(urlsplit(handoff["url"]).query)
        self.assertEqual(query, {"source": ["companies"], "state": ["FL"], "industry": ["Insurance"], "exclude_major_chains": ["0"]})


@override_settings(ZOOMINFO_ENABLED=True, ZOOMINFO_CLIENT_ID="test-id", ZOOMINFO_CLIENT_SECRET="test-secret", CELERY_BROKER_URL="", LEAD_FINDER_ENABLE_PUBLIC_HTTP=True)
class DiscoveryWorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rep = get_user_model().objects.create_user(username="discovery-rep", role="employee")
        self.client.force_login(self.rep)

    @patch("crm.zoominfo_api.requests.request")
    def test_default_finder_and_legacy_zoominfo_share_forms_without_api_calls(self, http):
        res = self.client.get(reverse("lead_finder"))
        self.assertEqual(res.context["finder_source"], "companies")
        self.assertEqual(res.context["form"]["page_size"].value(), 50)
        self.assertContains(res, "ZoomInfo company search")
        self.assertContains(res, "Public listings")
        self.assertContains(res, "Blank lead sheet")
        people = self.client.get(reverse("lead_finder"), {"source": "people", "company_id": "2001"})
        self.assertEqual(people.context["form"]["company_id"].value(), "2001")
        self.assertContains(people, "Contact availability")
        legacy = self.client.get(reverse("zoominfo_workspace"), {"kind": "people", "company_id": "2001"})
        self.assertEqual(legacy.context["finder_source"], "people")
        public = self.client.get(reverse("lead_finder"), {"source": "public"})
        self.assertContains(public, "data-finder-city")
        for query in ({"finder_batch": "1"}, {"finder_employee": str(self.rep.pk)}, {"page": "2"}):
            self.assertEqual(self.client.get(reverse("lead_finder"), query).context["finder_source"], "public")
        http.assert_not_called()

    @patch("crm.zoominfo_api.enrich")
    @patch("crm.zoominfo_api.search", return_value=([{"id": "2001", "name": "Example Insurance", "company": "Example Insurance"}], 230, True))
    def test_finder_search_uses_100_results_and_keeps_paging_criteria(self, search, enrich):
        res = self.client.post(reverse("lead_finder"), {"source": "companies", "industry": "insurance", "state": "FL", "page_size": "100", "exclude_major_chains": "on"})
        self.assertEqual(res.status_code, 302)
        run = ZoomInfoSearch.objects.get()
        self.assertEqual(run.page_size, 100)
        self.assertEqual(search.call_args.kwargs, {"page_size": 100, "sort": "name"})
        self.assertEqual(search.call_args.args[1]["state"], "Florida")
        self.assertTrue(search.call_args.args[1]["excludeDefunctCompanies"])
        self.assertContains(self.client.get(res.url), "source=people&amp;company_id=2001")
        self.client.post(reverse("zoominfo_page", args=[run.pk]), {"page": 2, "page_size": "25", "state": "CA"})
        self.assertEqual(search.call_args.args[1], run.criteria)
        self.assertEqual(search.call_args.args[2], 2)
        self.assertEqual(search.call_args.kwargs["page_size"], 100)
        self.assertFalse(LeadGenerationBatch.objects.exists())
        self.assertFalse(Lead.objects.exists())
        enrich.assert_not_called()

    @patch("crm.zoominfo_api.search", return_value=([], 0, False))
    def test_legacy_saved_pages_still_use_25_and_do_not_skip_records(self, search):
        run = ZoomInfoSearch.objects.create(user=self.rep, kind="companies", criteria={"state": "Florida"}, form_values={"state": "FL"}, has_next=True)
        self.client.post(reverse("zoominfo_page", args=[run.pk]), {"page": 2})
        self.assertEqual(search.call_args.kwargs["page_size"], 25)
        self.assertEqual(ZoomInfoSearch.objects.exclude(pk=run.pk).get().page_size, 25)

    @patch("crm.zoominfo_api.requests.request")
    def test_missing_configuration_shows_error_without_public_fallback_or_fake_results(self, http):
        with override_settings(ZOOMINFO_CLIENT_SECRET=""):
            res = self.client.post(reverse("lead_finder"), {"source": "companies", "industry": "insurance", "state": "FL"})
        self.assertContains(res, "Missing server settings: ZOOMINFO_CLIENT_SECRET")
        self.assertContains(res, "Search not completed")
        self.assertEqual(res.context["form"]["industry"].value(), "insurance")
        self.assertFalse(ZoomInfoSearch.objects.exists())
        self.assertFalse(LeadGenerationBatch.objects.exists())
        http.assert_not_called()

    @patch("crm.zoominfo_api.requests.request")
    def test_invalid_source_filters_and_client_access_never_contact_provider(self, http):
        self.assertEqual(self.client.get(reverse("lead_finder"), {"source": "unknown"}).status_code, 400)
        res = self.client.post(reverse("lead_finder"), {"source": "companies", "state": "FL", "page_size": "999"})
        self.assertTrue(res.context["form"].errors)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.rep)
        self.assertEqual(csrf.post(reverse("lead_finder"), {"source": "companies", "state": "FL"}).status_code, 403)
        customer = get_user_model().objects.create_user(username="discovery-customer", role="client")
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse("lead_finder")).status_code, 302)
        self.assertEqual(self.client.post(reverse("lead_finder"), {"source": "companies", "state": "FL"}).status_code, 302)
        http.assert_not_called()

    @patch("crm.zoominfo_api.search")
    def test_broader_filter_links_preserve_people_filters_and_do_not_search(self, search):
        values = {"state": "FL", "zip_code": "33101", "radius": 25, "industry": "Insurance", "job_title": "Owner OR President", "contact_details": "directPhone", "max_employees": 50, "page_size": 100, "exclude_major_chains": False}
        run = ZoomInfoSearch.objects.create(user=self.rep, kind="people", page_size=100, criteria={"state": "Florida", "zipCode": "33101", "employeeRangeMax": "50"}, form_values=values)
        res = self.client.get(reverse("zoominfo_results", args=[run.pk]))
        broader = res.context["broader_searches"][0]
        form_page = self.client.get(broader["url"])
        form = form_page.context["form"]
        self.assertEqual(form["job_title"].value(), "Owner OR President")
        self.assertEqual(form["contact_details"].value(), "directPhone")
        self.assertEqual(form["state"].value(), "FL")
        self.assertFalse(form["zip_code"].value())
        self.assertFalse(form["exclude_major_chains"].value())
        search.assert_not_called()
