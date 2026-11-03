from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Company, Lead, LeadActivity, LeadImport, ZoomInfoSearch
from .test_zoominfo_api import person_row, contact_resource


def company_row(company_id="2001", name="Example Motors"):
    return {
        "id": company_id, "name": name, "company": name, "company_id": company_id,
        "website": "https://example.test", "location": "Doral, Florida",
        "raw": {"id": company_id, "type": "Company", "attributes": {
            "name": name, "website": "example.test", "phone": "760-555-0100",
            "city": "Doral", "state": "Florida", "primaryIndustry": "Auto Repair",
        }},
    }


class SaveSearchResultsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.rep = User.objects.create_user(username="save-rep", role="employee")
        self.other = User.objects.create_user(username="save-other", role="employee")
        self.owner = User.objects.create_user(username="save-owner", role="owner")
        self.client.force_login(self.rep)
        self.http = patch("crm.zoominfo_api.requests.request").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.http.assert_not_called()

    def run_for(self, kind="companies", rows=None, user=None):
        return ZoomInfoSearch.objects.create(
            user=user or self.rep, kind=kind,
            results=rows or ([company_row()] if kind == "companies" else [person_row()]),
        )

    def save(self, run, ids=None, **extra):
        return self.client.post(reverse("zoominfo_add_to_crm", args=[run.pk]), {
            "selected": ids or [row["id"] for row in run.results], **extra,
        })

    def test_company_selection_saves_to_visible_pipeline_and_repeat_is_idempotent(self):
        run = self.run_for(rows=[company_row(), company_row("2002", "Another Garage")])
        page = self.client.get(reverse("zoominfo_results", args=[run.pk]))
        self.assertContains(page, "Select all on this page")
        self.assertContains(page, "Add to CRM / pipeline")
        self.assertContains(page, 'name="selected"', count=2)
        response = self.save(run, ["2001"], assigned_to=self.other.pk, business_name="Forged name")
        self.assertRedirects(response, reverse("sales_pipeline"))
        lead = Lead.objects.get()
        self.assertEqual(lead.business_name, "Example Motors")
        self.assertEqual(lead.assigned_to, self.rep)
        self.assertEqual(lead.company.zoominfo_id, "2001")
        self.assertEqual(lead.zoominfo_profile.identity_key, "company:2001")
        self.assertEqual(lead.phone, "760-555-0100")
        self.assertEqual(lead.status, "new")
        self.assertIsNone(lead.last_contact_at)
        self.assertFalse(LeadActivity.objects.filter(activity_type="call").exists())
        self.save(run, ["2001"])
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(LeadImport.objects.count(), 1)
        self.assertContains(self.client.get(reverse("sales_pipeline")), "Example Motors")
        self.assertContains(self.client.get(reverse("zoominfo_results", args=[run.pk])), "In pipeline")

    def test_fresh_search_matches_company_and_preserves_sales_progress(self):
        self.save(self.run_for())
        lead = Lead.objects.get()
        lead.status, lead.notes = "do_not_contact", "Keep our existing notes"
        lead.save()
        updated = company_row()
        updated["raw"]["attributes"]["employeeCount"] = 23
        self.save(self.run_for(rows=[updated]))
        self.assertEqual(Lead.objects.count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "do_not_contact")
        self.assertEqual(lead.notes, "Keep our existing notes")
        self.assertEqual(lead.company.source_data["Employees"], "23")

    def test_company_matches_existing_business_only_lead(self):
        lead = Lead.objects.create(business_name="Example Motors", website="https://example.test", city="Doral", state="Florida", assigned_to=self.rep)
        self.save(self.run_for())
        self.assertEqual(Lead.objects.count(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.company.zoominfo_id, "2001")

    def test_people_save_missing_details_as_blank_and_later_enrichment_merges(self):
        row = person_row()
        for field in ("email", "phone"):
            row["raw"]["attributes"].pop(field)
        run = self.run_for("people", [row])
        self.save(run)
        lead = Lead.objects.get()
        self.assertEqual(lead.name, "Alex Rivera")
        self.assertEqual((lead.email, lead.phone), ("", ""))
        self.assertEqual(lead.zoominfo_profile.contact_id, "1001")
        lead.status, lead.notes = "warm_lead", "Interested in a demo"
        lead.save()
        with patch("crm.zoominfo_api.output_fields", return_value=["id", "email", "phone"]), patch("crm.zoominfo_api.enrich", return_value={"data": [contact_resource()]}):
            response = self.client.post(reverse("zoominfo_details", args=[run.pk]), {"selected": ["1001"]})
        run.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.client.post(reverse("lead_import_confirm", args=[run.preview_id]))
        lead.refresh_from_db()
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(lead.email, "alex@example.test")
        self.assertEqual(lead.status, "warm_lead")
        self.assertEqual(lead.notes, "Interested in a demo")

    def test_people_and_company_are_distinct_records_in_one_company(self):
        self.save(self.run_for("people"))
        self.save(self.run_for())
        self.assertEqual(Lead.objects.count(), 2)
        self.assertEqual(Company.objects.count(), 1)

    def test_do_not_call_flag_is_preserved(self):
        row = person_row()
        row["raw"]["attributes"]["directPhoneDoNotCall"] = True
        self.save(self.run_for("people", [row]))
        self.assertEqual(Lead.objects.get().status, "do_not_contact")

    def test_other_employees_records_are_not_reassigned_or_exposed(self):
        self.client.force_login(self.other)
        self.save(self.run_for(user=self.other))
        self.client.force_login(self.rep)
        run = self.run_for()
        self.save(run)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(Lead.objects.get().assigned_to, self.other)
        self.assertEqual(LeadImport.objects.latest("pk").skipped_count, 1)
        self.assertNotContains(self.client.get(reverse("zoominfo_results", args=[run.pk])), "In pipeline")

    def test_managers_can_assign_selected_results(self):
        self.client.force_login(self.owner)
        self.save(self.run_for(user=self.owner), assigned_to=self.other.pk)
        self.assertEqual(Lead.objects.get().assigned_to, self.other)

    def test_private_post_csrf_expiry_and_selection_boundaries(self):
        run = self.run_for()
        url = reverse("zoominfo_add_to_crm", args=[run.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for selection in ([], ["9999"], ["2001", "9999"]):
            self.client.post(url, {"selected": selection})
            self.assertFalse(Lead.objects.exists())
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.rep)
        self.assertEqual(browser.post(url, {"selected": ["2001"]}).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.save(run).status_code, 404)
        self.client.force_login(self.rep)
        ZoomInfoSearch.objects.filter(pk=run.pk).update(created_at=timezone.now()-timedelta(days=2))
        self.save(run)
        self.assertFalse(Lead.objects.exists())
