import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature, override_settings
from django.urls import reverse

from .importers import import_lead_file
from .lead_finder import DirectoryLead, create_generation_batch, generate_leads_for_batch, convert_staging_to_crm_lead
from .models import Company, Lead, LeadGenerationBatch, LeadStaging, ZoomInfoSearch
from .ownership import CompanyOwnedElsewhere, claim_company
from .test_zoominfo_api import person_row
from .test_zoominfo_save import company_row
from .sheet_files import make_xlsx


class CompanyOwnershipTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.first = User.objects.create_user(username="first-agent", role="employee")
        self.second = User.objects.create_user(username="second-agent", role="employee")
        self.client.force_login(self.second)

    def first_lead(self):
        return Lead.objects.create(business_name="Example Motors", website="https://www.example.test", city="Doral", state="FL", phone="7605550100", assigned_to=self.first)

    def test_excel_duplicate_with_changed_contact_details_keeps_first_owner_and_flags_row(self):
        lead = self.first_lead()
        schema = [{"label":field, "type":"text", "choices":[]} for field in ["business_name", "website", "phone", "email", "city", "state"]]
        content = make_xlsx(schema, [["Example Motors LLC", "http://example.test/contact", "7605550199", "new@example.test", "Doral", "Florida"]], kind="prospects")
        upload = SimpleUploadedFile("prospects.xlsx", content)
        report, parsed = import_lead_file(upload, uploaded_by=self.second, force_assigned_to=self.second)
        self.assertFalse(parsed.errors)
        self.assertEqual((report.imported_count, report.duplicate_count, report.skipped_count), (0, 1, 1))
        self.assertEqual(report.import_summary["duplicate_rows"][0]["sheet"], "Prospects")
        self.assertEqual(Lead.objects.count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to, self.first)
        self.assertEqual(lead.company.owner, self.first)
        self.assertContains(self.client.get(reverse("lead_import_detail", args=[report.pk])), "Duplicates skipped")

    def test_zoominfo_company_and_new_person_hidden_and_stale_saves_blocked(self):
        runs = [ZoomInfoSearch.objects.create(user=self.second, kind=kind, results=[row]) for kind, row in [("companies", company_row()), ("people", person_row())]]
        self.first_lead()
        for run in runs:
            page = self.client.get(reverse("zoominfo_results", args=[run.pk]))
            self.assertContains(page, "another agent already owns")
            self.assertNotContains(page, "Example Motors")
            self.assertNotContains(page, 'name="selected"')
            self.client.post(reverse("zoominfo_add_to_crm", args=[run.pk]), {"selected":[run.results[0]["id"]]})
        self.assertEqual(Lead.objects.count(), 1)
        with patch("crm.zoominfo_api.enrich") as enrich, patch("crm.zoominfo_api.output_fields") as fields:
            self.client.post(reverse("zoominfo_details", args=[runs[1].pk]), {"selected":["1001"]})
        enrich.assert_not_called(); fields.assert_not_called()

    @override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=True, CELERY_BROKER_URL="")
    def test_listing_discovery_does_not_claim_but_first_promotion_blocks_other_agent(self):
        from unittest.mock import Mock
        provider = Mock(name="fixture")
        provider.name = "fixture"
        provider.summary = {}
        provider.search.return_value = [DirectoryLead(business_name="Example Motors", phone_number="7605550100", industry="Auto Repair", website="https://example.test", city="Doral", state="FL")]
        batches = [create_generation_batch(employee=user, industry="Auto Repair", location="Doral, FL", quantity=5) for user in [self.first,self.second]]
        for batch in batches:
            generate_leads_for_batch(batch.pk, providers=[provider])
        self.assertEqual(LeadStaging.objects.count(), 2)
        self.assertFalse(Company.objects.exists())
        first = LeadStaging.objects.get(batch=batches[0])
        second = LeadStaging.objects.get(batch=batches[1])
        convert_staging_to_crm_lead(first, employee=self.first, contacted=False)
        page = self.client.get(reverse("lead_generation_batch_detail", args=[batches[1].pk]))
        self.assertNotContains(page, "Example Motors")
        with self.assertRaises(ValueError):
            convert_staging_to_crm_lead(second, employee=self.second, contacted=False)
        third = create_generation_batch(employee=self.second, industry="Auto Repair", location="Miami, FL", quantity=5)
        generate_leads_for_batch(third.pk, providers=[provider])
        self.assertFalse(third.staged_leads.exists())
        self.assertEqual(Lead.objects.count(), 1)

    def test_manual_and_sheet_entry_cannot_claim_another_agents_company(self):
        self.first_lead()
        response = self.client.post(reverse("lead_create"), {"business_name":"Example Motors LLC", "website":"https://example.test", "status":"new", "lead_temperature":"cold", "value":"0"})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Duplicate company")
        sheet = self.client.get(reverse("lead_sheet_new")).context["sheet_data"]
        response = self.client.post(reverse("lead_sheet_save"), json.dumps({
            "snapshot":sheet["snapshot"], "mutation_id":str(uuid.uuid4()), "title":"New leads",
            "rows":[{"key":str(uuid.uuid4()),"changes":{"business_name":"Example Motors LLC","website":"https://example.test"}}],
        }), content_type="application/json")
        self.assertEqual(response.status_code,400)
        self.assertIn("Duplicate company",response.json()["error"])
        self.assertEqual(Lead.objects.count(),1)
        own = Lead.objects.create(business_name="Different business", assigned_to=self.second)
        response = self.client.post(reverse("lead_edit", args=[own.pk]), {"business_name":"Example Motors LLC", "website":"https://example.test", "status":"new", "lead_temperature":"cold", "value":"0"})
        self.assertContains(response, "Duplicate company")
        own.refresh_from_db()
        self.assertEqual(own.business_name, "Different business")

    def test_skipped_existing_contact_does_not_claim_a_new_company(self):
        from .zoominfo_save import search_csv
        first = SimpleUploadedFile("first.csv", search_csv("people", [person_row()]))
        import_lead_file(first, force_assigned_to=self.first)
        moved = person_row()
        moved.update(company_id="9999", company="Changed Employer", website="https://changed.test")
        moved["raw"]["attributes"]["company"] = {"id":"9999", "name":"Changed Employer", "website":"changed.test"}
        second = SimpleUploadedFile("second.csv", search_csv("people", [moved]))
        report, _ = import_lead_file(second, force_assigned_to=self.second)
        self.assertEqual(report.skipped_count, 1)
        self.assertEqual(Company.objects.count(), 1)
        self.assertFalse(Company.objects.filter(owner=self.second).exists())

    def test_backfill_keeps_earliest_record_owner_across_historical_company_aliases(self):
        from importlib import import_module
        from django.apps import apps
        from .models import CompanyIdentity
        early = Company.objects.create(name="Example Motors LLC", website="https://example.test")
        late = Company.objects.create(name="Example Motors", city="Doral", state="FL")
        bridge = Company.objects.create(name="Example Motors", website="https://example.test", city="Doral", state="Florida")
        leads = Lead.objects.bulk_create([
            Lead(business_name=early.name, company=early, assigned_to=self.first),
            Lead(business_name=late.name, company=late, assigned_to=self.second),
        ])
        migration = import_module("crm.migrations.0025_company_ownership")
        migration.seed_ownership(apps, None)
        self.assertEqual(set(Company.objects.values_list("owner_id", flat=True)), {self.first.pk})
        self.assertEqual(set(CompanyIdentity.objects.values_list("company_id", flat=True)), {early.pk})
        # Backfill establishes claims without rewriting historical leads.
        leads[1].refresh_from_db()
        self.assertEqual(leads[1].assigned_to, self.second)

    def test_matching_normalizes_business_suffix_state_domain_and_keeps_shared_sites_separate(self):
        company = claim_company({"business_name":"Example Motors, LLC", "city":"Doral", "state":"Florida"}, self.first)
        with self.assertRaises(CompanyOwnedElsewhere):
            claim_company({"business_name":"Example Motors", "city":"Doral", "state":"FL"}, self.second)
        first = claim_company({"business_name":"Different Cafe", "website":"https://facebook.com/cafe"}, self.first)
        second = claim_company({"business_name":"Different Bakery", "website":"https://facebook.com/bakery"}, self.second)
        self.assertNotEqual(first.pk,second.pk)


class ConcurrentCompanyOwnershipTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_simultaneous_agents_get_one_company_owner(self):
        User = get_user_model()
        users = [User.objects.create_user(username=f"race-{i}", role="employee") for i in range(2)]
        barrier = Barrier(2)
        def claim(user_id):
            close_old_connections()
            try:
                user = User.objects.get(pk=user_id)
                barrier.wait(timeout=10)
                try:
                    return claim_company({"business_name":"Race Motors", "website":"https://race.example.test"},user).owner_id
                except CompanyOwnedElsewhere:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim,[user.pk for user in users]))
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertEqual(Company.objects.count(),1)
        self.assertIn(Company.objects.get().owner_id,results)
