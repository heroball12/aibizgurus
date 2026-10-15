from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import ActivityLog, EmployeeLeadEvent
from .models import Lead, LeadActivity, LeadNote


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", TIME_ZONE="America/Los_Angeles")
class PipelineFilterTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="pipeline-owner", role="owner")
        self.rep = User.objects.create_user(username="pipeline-rep", role="employee", first_name="Erika")
        self.other = User.objects.create_user(username="pipeline-other", role="employee")
        self.inactive = User.objects.create_user(username="former-employee", role="employee", is_active=False)
        self.client.force_login(self.owner)
        self.lead = Lead.objects.create(business_name="Cedar Plumbing", assigned_to=self.rep, industry="Plumbing",
            city="Temecula", state="CA", phone="7605550100", email="cedar@example.com", website="https://example.com",
            source="Purchased list", source_file="prospects.xlsx", source_sheet="West", status="warm_lead", lead_temperature="warm")
        self.old = Lead.objects.create(business_name="Older lead", assigned_to=self.other)
        self.untouched = Lead.objects.create(business_name="New untouched")
        Lead.objects.create(business_name="Former rep lead", assigned_to=self.inactive)
        Lead.objects.create(business_name="Private customer", lead_type="client_customer", assigned_to=self.rep)
        Lead.objects.create(business_name="Archived", archived=True, assigned_to=self.rep)
        Lead.objects.filter(pk=self.old.pk).update(created_at=timezone.now() - timedelta(days=60))

    def page(self, **filters):
        return self.client.get(reverse("sales_pipeline"), filters)

    def ids(self, **filters):
        return [row.pk for row in self.page(**filters).context["page_obj"]]

    def at(self, record, stamp):
        type(record).objects.filter(pk=record.pk).update(created_at=stamp)

    def test_owner_filters_combine_and_include_inactive_assignments(self):
        self.assertEqual(self.ids(assigned_to=self.rep.pk, industry="Plumbing", state="CA", city="temec",
            status="warm_lead", temperature="warm", lead_source="Purchased list", source_file="prospects.xlsx",
            source_sheet="West", phone="yes", email="yes", website="yes"), [self.lead.pk])
        self.assertEqual(self.ids(assigned_to="unassigned"), [self.untouched.pk])
        self.assertContains(self.page(), "former-employee (inactive)")
        self.assertEqual(len(self.ids(assigned_to=self.inactive.pk)), 1)
        self.assertNotContains(self.page(), "Private customer")
        self.assertNotContains(self.page(), ">Archived<")

    def test_last_activity_uses_latest_historical_call_note_event_audit_or_contact(self):
        now = timezone.now()
        call = LeadActivity.objects.create(lead=self.lead, activity_type="call")
        self.at(call, now - timedelta(days=20))
        note = LeadNote.objects.create(lead=self.lead, note="Called owner")
        self.at(note, now - timedelta(days=10))
        event = EmployeeLeadEvent.objects.create(lead=self.lead, lead_key=self.lead.pk, lead_name="Cedar",
            actor=self.rep, actor_name="Erika", kind="updated", historical=True)
        self.at(event, now - timedelta(days=5))
        audit = ActivityLog.objects.create(model_label="crm.Lead", object_id=str(self.lead.pk), action="update")
        self.at(audit, now - timedelta(days=2))
        self.assertEqual(self.ids(activity="7"), [self.lead.pk])
        record = next(row for row in self.page().context["page_obj"] if row.pk == self.lead.pk)
        self.assertEqual(record.last_activity_at, now - timedelta(days=2))
        Lead.objects.filter(pk=self.lead.pk).update(last_contact_at=now - timedelta(hours=1))
        record = next(row for row in self.page().context["page_obj"] if row.pk == self.lead.pk)
        self.assertEqual(record.last_activity_at, now - timedelta(hours=1))
        self.assertEqual(self.ids(contacted="yes"), [self.lead.pk])
        self.assertEqual(len(self.page(activity="7").context["page_obj"]), 1)  # No joined duplicates.

    def test_creation_and_import_alone_are_not_activity_and_new_leads_are_not_stale(self):
        LeadActivity.objects.create(lead=self.untouched, activity_type="imported_note")
        EmployeeLeadEvent.objects.create(lead=self.untouched, lead_key=self.untouched.pk, lead_name="Untouched",
            actor=self.rep, actor_name="Erika", kind="created")
        self.assertIn(self.untouched.pk, self.ids(activity="never"))
        self.assertEqual(self.ids(activity="stale14"), [self.old.pk])
        self.assertEqual(self.ids(activity="7"), [])

    def test_custom_activity_range_includes_end_day_and_rejects_invalid_ranges(self):
        stamp = timezone.make_aware(datetime(2026, 9, 30, 23, 59, 59))
        self.at(LeadActivity.objects.create(lead=self.lead, activity_type="call"), stamp)
        self.at(LeadActivity.objects.create(lead=self.old, activity_type="call"), stamp + timedelta(seconds=1))
        self.assertEqual(self.ids(activity_from="2026-09-30", activity_to="2026-09-30"), [self.lead.pk])
        for filters in [dict(activity_from="2026-10-02", activity_to="2026-09-30"),
                        dict(activity_from="invalid"), dict(created_to="9999-12-31"),
                        dict(sort="unknown"), dict(activity="stale-huge")]:
            page = self.page(**filters)
            self.assertEqual(page.status_code, 200)
            self.assertTrue(page.context["pipeline_form"].errors)
            self.assertEqual(list(page.context["page_obj"]), [])

    def test_sort_and_stage_links_keep_filters_and_matching_stage_counts(self):
        now = timezone.now()
        Lead.objects.filter(pk=self.lead.pk).update(last_contact_at=now)
        Lead.objects.filter(pk=self.old.pk).update(last_contact_at=now - timedelta(days=10))
        self.assertEqual(self.ids(sort="activity_oldest")[:2], [self.old.pk, self.lead.pk])
        self.assertEqual(self.ids(sort="activity_newest")[:2], [self.lead.pk, self.old.pk])
        page = self.page(assigned_to=self.rep.pk, activity="30", sort="activity_newest", page=4)
        conversation = next(row for row in page.context["stages"] if row["key"] == "conversation")
        self.assertEqual(conversation["count"], 1)
        self.assertEqual(parse_qs(urlsplit(conversation["url"]).query),
            {"assigned_to": [str(self.rep.pk)], "activity": ["30"], "sort": ["activity_newest"], "stage": ["conversation"]})
        self.assertEqual(self.ids(assigned_to=self.rep.pk, stage="new"), [])
        self.assertEqual(self.ids(assigned_to=self.rep.pk, stage="conversation"), [self.lead.pk])

    def test_followups_appointments_created_dates_and_review_filters(self):
        today = timezone.localdate()
        Lead.objects.filter(pk=self.lead.pk).update(follow_up_date=today, appointment_at=timezone.now()+timedelta(days=2), needs_review=True)
        self.assertEqual(self.ids(follow_up="today", appointment="upcoming", needs_review="yes"), [self.lead.pk])
        self.assertEqual(self.ids(created_to=(today-timedelta(days=30)).isoformat()), [self.old.pk])
        self.assertNotIn(self.lead.pk, self.ids(email="no"))
        Lead.objects.filter(pk=self.lead.pk).update(status="do_not_contact")
        self.assertEqual(self.ids(follow_up="due"), [])

    def test_spreadsheet_and_csv_match_pipeline_and_employee_scope_cannot_be_bypassed(self):
        query = {"source": "pipeline", "assigned_to": self.rep.pk, "industry": "Plumbing", "email": "yes", "format": "csv"}
        export = self.client.get(reverse("lead_sheet_export"), query)
        self.assertEqual(export.status_code, 200)
        content = export.content.decode()
        self.assertIn("Cedar Plumbing", content)
        self.assertNotIn("Older lead", content)
        sheet = self.client.get(reverse("lead_sheet_new"), query)
        self.assertEqual(sheet.status_code, 200)
        self.client.force_login(self.rep)
        self.assertEqual(self.ids(), [self.lead.pk])
        self.assertEqual(self.ids(assigned_to=self.other.pk), [])
        self.assertNotContains(self.page(), "All employees")
        query["assigned_to"] = self.other.pk
        export = self.client.get(reverse("lead_sheet_export"), query)
        self.assertNotIn("Older lead", export.content.decode())
