import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from django.forms.models import model_to_dict
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from crm.forms import LeadForm
from crm.models import Lead, LeadActivity, LeadNote
from .models import ActivityLog, EmployeeLeadEvent, TimeClockEntry
from .performance import date_window, performance_context
from .threadlocal import set_current_request, clear_current_request


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmployeePerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="perf-owner", role="owner")
        cls.rep = User.objects.create_user(username="perf-rep", role="employee", first_name="Erin")
        cls.other = User.objects.create_user(username="perf-other", role="employee")
        cls.admin = User.objects.create_user(username="perf-admin", role="admin")
        cls.customer = User.objects.create_user(username="perf-client", role="client")
        cls.lead = Lead.objects.create(business_name="Employee Plumbing", assigned_to=cls.rep)
        cls.other_lead = Lead.objects.create(business_name="Other Business", assigned_to=cls.other)

    def setUp(self):
        self.client.force_login(self.rep)
        self.addCleanup(clear_current_request)

    def metrics(self, employee=None, **params):
        request = RequestFactory().get("/owner/", {"period": "all", **params})
        request.user = self.owner
        return performance_context(request, [employee or self.rep])["employee_rows"][0]

    def edit(self, lead=None, **changes):
        lead = lead or self.lead
        lead.refresh_from_db()
        values = model_to_dict(lead, fields=LeadForm.Meta.fields)
        values = {key: value if value is not None else "" for key, value in values.items()}
        values.update(changes)
        return self.client.post(reverse("lead_edit", args=[lead.pk]), values)

    def test_manual_edits_notes_and_multiple_saves_count_once(self):
        self.assertEqual(self.edit(notes="Reached the owner").status_code, 302)
        self.assertEqual(self.metrics()["calls"], 1)
        self.assertEqual(self.edit(notes="Reached the owner").status_code, 302)
        self.assertEqual(self.metrics()["calls"], 1)
        self.client.post(reverse("lead_detail", args=[self.lead.pk]), {"note": "Callback tomorrow"})
        self.assertEqual(self.metrics()["calls"], 2)
        request = RequestFactory().post("/crm/leads/1/edit/")
        request.user = self.rep
        request.resolver_match = SimpleNamespace(url_name="lead_edit")
        set_current_request(request)
        self.lead.refresh_from_db()
        self.lead.notes = "One request"
        self.lead.save()
        self.lead.status = "warm_lead"
        self.lead.save()
        LeadNote.objects.create(lead=self.lead, user=self.rep, note="Also a note")
        clear_current_request()
        self.assertEqual(self.metrics()["calls"], 3)
        event = EmployeeLeadEvent.objects.first()
        self.assertEqual(event.changes["notes"]["before"], "Reached the owner")
        self.assertEqual(event.changes["notes"]["after"], "One request")

    def test_failed_validation_reads_and_background_changes_are_not_calls(self):
        self.client.get(reverse("lead_detail", args=[self.lead.pk]))
        self.edit(status="invalid")
        self.lead.notes = "Background data"
        self.lead.save()
        self.assertEqual(self.metrics()["calls"], 0)

    def test_booking_requires_time_and_is_not_duplicated(self):
        url = reverse("lead_progress", args=[self.lead.pk])
        self.assertEqual(self.client.post(url, {"action": "assessment", "assessment-confirmed": "on"}).status_code, 400)
        self.assertEqual(self.metrics()["booked"], 0)
        payload = {"action": "assessment", "assessment-confirmed": "on", "assessment-appointment_at": "2026-11-01T10:00"}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.metrics()["calls"], 1)
        self.assertEqual(self.metrics()["booked"], 1)
        payload["assessment-completed"] = "on"
        self.client.post(url, payload)
        self.assertEqual(self.metrics()["completed"], 1)
        self.assertEqual(self.metrics()["booked"], 1)
        self.assertEqual(self.metrics()["booking_rate"], 100)

    def test_status_without_confirmed_time_does_not_book_assessment(self):
        self.edit(status="appointment_scheduled")
        self.assertEqual(self.metrics()["calls"], 1)
        self.assertEqual(self.metrics()["booked"], 0)

    def test_reassignment_deletion_and_manager_edits_preserve_actor_credit(self):
        self.edit(notes="Rep work")
        self.client.force_login(self.owner)
        self.edit(notes="Owner edit", assigned_to=self.other.pk)
        self.assertEqual(self.metrics()["calls"], 1)
        self.assertEqual(self.metrics(self.other)["calls"], 0)
        self.assertEqual(self.metrics(self.owner)["calls"], 1)
        self.client.post(reverse("lead_delete", args=[self.lead.pk]))
        self.assertEqual(self.metrics()["calls"], 1)
        event = EmployeeLeadEvent.objects.get(actor=self.rep)
        self.assertIsNone(event.lead)
        self.assertEqual(event.lead_name, "Employee Plumbing")
        self.assertEqual(EmployeeLeadEvent.objects.filter(kind="deleted").count(), 1)

    def test_bulk_saves_count_each_changed_lead_once_and_stay_scoped(self):
        another = Lead.objects.create(business_name="Second", assigned_to=self.rep)
        payload = {"action": "update_selected", "lead_ids": [self.lead.pk, another.pk, self.other_lead.pk], "status": "attempted", "employee_scope": self.other.pk}
        self.client.post(reverse("lead_bulk_action"), payload)
        self.assertEqual(self.metrics()["calls"], 2)
        self.other_lead.refresh_from_db()
        self.assertEqual(self.other_lead.status, "new")
        self.client.post(reverse("lead_bulk_action"), payload)
        self.assertEqual(self.metrics()["calls"], 2)

    def test_owner_delete_filtered_cannot_escape_employee_scope(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("lead_bulk_action"), {"action": "delete_filtered", "employee_scope": self.rep.pk})
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertTrue(Lead.objects.filter(pk=self.other_lead.pk).exists())

    def test_archived_leads_can_be_managed_and_create_is_preassigned(self):
        self.lead.archived = True
        self.lead.save()
        self.assertEqual(self.client.get(reverse("lead_edit", args=[self.lead.pk])).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("lead_edit", args=[self.lead.pk])).status_code, 200)
        response = self.client.get(reverse("lead_create"), {"assigned_to": self.rep.pk})
        self.assertEqual(str(response.context["form"].initial["assigned_to"]), str(self.rep.pk))
        detail = self.client.get(reverse("staff_performance", args=[self.rep.pk]))
        self.assertContains(detail, "Employee Plumbing")
        self.assertContains(detail, 'name="employee_scope"')
        response = self.client.post(reverse("lead_progress", args=[self.lead.pk]), {"action": "progress", "outcome-outcome": "warm_lead", "outcome-note": "Archived review"})
        self.assertEqual(response.status_code, 302)

    def test_spreadsheet_retry_does_not_duplicate_call_credit(self):
        sheet = self.client.get(reverse("lead_sheet_new"), {"source": "all"}).context["sheet_data"]
        payload = {"snapshot": sheet["snapshot"], "mutation_id": str(uuid.uuid4()), "title": "Employee sheet", "rows": [{"key": sheet["rows"][0]["key"], "changes": {"notes": "Spoke with the owner"}}]}
        for _ in range(2):
            response = self.client.post(reverse("lead_sheet_save"), json.dumps(payload), content_type="application/json")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.metrics()["calls"], 1)

    def test_rolled_back_sheet_save_leaves_no_events(self):
        request = RequestFactory().post("/crm/sheets/save/")
        request.user = self.rep
        request.resolver_match = SimpleNamespace(url_name="lead_sheet_save")
        set_current_request(request)
        with self.assertRaises(ValueError):
            with transaction.atomic():
                self.lead.notes = "Rolled back"
                self.lead.save()
                raise ValueError("Invalid second row")
        clear_current_request()
        self.assertFalse(EmployeeLeadEvent.objects.exists())

    def test_permissions_for_overview_activity_export_and_employee_leads(self):
        urls = [reverse("staff_users"), reverse("staff_performance", args=[self.other.pk]), reverse("staff_activity", args=[self.other.pk]), reverse("employee_metrics_export")]
        for user in [self.rep, self.customer]:
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse("lead_edit", args=[self.other_lead.pk])).status_code, 404)
        for user in [self.owner, self.admin]:
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_date_boundaries_shift_clipping_and_invalid_dates(self):
        self.edit(notes="A dated call")
        midnight = timezone.make_aware(datetime(2026, 9, 20))
        EmployeeLeadEvent.objects.update(created_at=midnight)
        TimeClockEntry.objects.create(employee=self.rep, clock_in=midnight-timedelta(hours=2), clock_out=midnight+timedelta(hours=3))
        row = self.metrics(period="custom", start="2026-09-20", end="2026-09-20")
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["hours"], 3)
        self.assertEqual(self.metrics(period="custom", start="2026-09-19", end="2026-09-19")["calls"], 0)
        for value in ["invalid", "2026-02-31", "9999-12-31"]:
            self.assertTrue(date_window({"period": "custom", "start": value, "end": value})["error"])

    def test_research_changes_never_become_calls_and_login_is_logged(self):
        request = RequestFactory().post("/crm/leads/1/research/")
        request.user = self.rep
        request.resolver_match = SimpleNamespace(url_name="lead_research")
        set_current_request(request)
        self.lead.website_review = {"summary": "Website checked"}
        self.lead.save(update_fields=["website_review"])
        clear_current_request()
        self.assertEqual(self.metrics()["calls"], 0)
        self.rep.set_password("Local-test-password-91")
        self.rep.save()
        self.client.logout()
        self.client.post(reverse("login"), {"username": self.rep.username, "password": "Local-test-password-91"})
        self.assertTrue(ActivityLog.objects.filter(actor=self.rep, action="login").exists())

    def test_explicit_call_is_counted_once_alongside_lead_update(self):
        request = RequestFactory().post("/crm/leads/1/edit/")
        request.user = self.rep
        request.resolver_match = SimpleNamespace(url_name="lead_edit")
        set_current_request(request)
        self.lead.status = "attempted"
        self.lead.save()
        LeadActivity.objects.create(lead=self.lead, user=self.rep, activity_type="call")
        clear_current_request()
        self.assertEqual(self.metrics()["calls"], 1)

    def test_activity_is_actor_scoped_paginated_and_escaped(self):
        self.edit(notes="<script>alert(1)</script>")
        self.client.force_login(self.owner)
        self.edit(notes="Manager-only entry")
        response = self.client.get(reverse("staff_activity", args=[self.rep.pk]), {"period": "all"})
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "Manager-only entry")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_dashboard_has_columns_export_and_no_outreach_dependency(self):
        self.client.force_login(self.owner)
        for name in ["owner_dashboard", "ops_dashboard", "staff_users"]:
            response = self.client.get(reverse(name))
            self.assertContains(response, "Assessments booked")
            self.assertContains(response, "Calls / updates")
            self.assertContains(response, reverse("staff_performance", args=[self.rep.pk]))
        self.rep.first_name = "=FORMULA()"
        self.rep.save()
        response = self.client.get(reverse("employee_metrics_export"))
        self.assertContains(response, "'=FORMULA()")


    def test_employee_search_and_inactive_lead_edit_preserve_scope(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("staff_users"), {"employee_q": "Erin"})
        self.assertEqual([r["employee"].pk for r in response.context["employee_rows"]], [self.rep.pk])
        self.rep.is_active = False
        self.rep.save()
        self.assertEqual(self.edit(notes="Manager can edit inactive employee's lead").status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_to_id, self.rep.pk)

    def test_outcome_note_counts_even_when_outcome_fields_are_unchanged(self):
        self.lead.status = "closed_won"
        self.lead.lead_temperature = "closed"
        self.lead.save()
        self.client.post(reverse("lead_progress", args=[self.lead.pk]), {"action": "progress", "outcome-outcome": "closed_won", "outcome-note": "New follow-up details"})
        self.assertEqual(self.metrics()["calls"], 1)
        self.assertEqual(self.metrics()["won"], 0)
