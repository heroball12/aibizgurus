import json
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .directory_locations import city_and_state, resolve_city
from .forms import LeadFinderForm
from .lead_finder import (
    DirectoryLead,
    DirectoryError,
    OpenStreetMapProvider,
    create_generation_batch,
    generate_leads_for_batch,
    convert_staging_to_crm_lead,
)
from .models import Lead, LeadGenerationBatch, LeadStaging


@override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=True, CELERY_BROKER_URL="")
class LeadFinderRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user(username="finder-owner", role="owner")
        self.rep = User.objects.create_user(username="finder-rep", role="employee")
        self.other = User.objects.create_user(username="finder-other", role="employee")
        self.client.force_login(self.rep)

    def batch(self, **extra):
        return LeadGenerationBatch.objects.create(
            employee=self.rep,
            industry="Restaurant",
            location="San Diego, CA",
            quantity_requested=5,
            **extra
        )

    def response(self, elements, **extra):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"elements": elements, **extra}
        ).encode()
        return response

    def test_location_variations_are_scoped_and_broad_searches_rejected(self):
        for value in [
            "san diego, ca",
            "san diego California",
            "san diego, California, USA",
        ]:
            self.assertEqual(city_and_state(value), ("san diego", "CA"))
        self.assertEqual(city_and_state("Portland, Oregon"), ("Portland", "OR"))
        for value in ["", "US", "California", "90210", "London, UK", "San Diego"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                city_and_state(value)
        self.assertTrue(
            LeadFinderForm(
                {
                    "industry": "other",
                    "custom_industry": "Plumber",
                    "location": "San Diego California",
                    "quantity": "5",
                }
            ).is_valid()
        )
        self.assertFalse(
            LeadFinderForm({"industry": "Restaurant", "quantity": "5"}).is_valid()
        )
        self.assertEqual(resolve_city("san diego California")[:2], ("San Diego", "CA"))
        self.assertEqual(resolve_city("Honolulu HI")[:2], ("Urban Honolulu", "HI"))
        self.assertEqual(resolve_city("New York City NY")[:2], ("New York", "NY"))
        self.assertEqual(resolve_city("St. Louis MO")[:2], ("St. Louis", "MO"))
        self.assertFalse(
            LeadFinderForm(
                {
                    "industry": "Restaurant",
                    "quantity": "5",
                    "location": "Made Up City CA",
                }
            ).is_valid()
        )

    @patch("crm.lead_finder.request.urlopen")
    def test_provider_keeps_website_email_and_phone_and_filters_empty_contacts(
        self, urlopen
    ):
        urlopen.return_value.__enter__.return_value = self.response(
            [
                {"type": "count", "tags": {"areas": "1"}},
                {
                    "type": "node",
                    "id": 1,
                    "tags": {"name": "Website Cafe", "website": "example.com"},
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {
                        "name": "Phone Cafe",
                        "contact:phone": "+1 619 555 0100; +1 619 555 0101",
                    },
                },
                {
                    "type": "node",
                    "id": 3,
                    "tags": {
                        "name": "Email Cafe",
                        "contact:email": "hello@example.com",
                    },
                },
                {
                    "type": "node",
                    "id": 4,
                    "tags": {
                        "name": "Empty Cafe",
                        "phone": "12",
                        "website": "javascript:alert(1)",
                        "email": "invalid",
                    },
                },
            ]
        )
        provider = OpenStreetMapProvider()
        rows = provider.search(
            industry="Restaurant", location="san diego California", limit=5
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].business_name, "Phone Cafe")
        self.assertEqual(rows[0].phone_number, "(619) 555-0100")
        self.assertTrue(any(row.email == "hello@example.com" for row in rows))
        self.assertEqual(provider.summary["missing_contact"], 1)
        query = parse_qs(urlsplit(urlopen.call_args.args[0].full_url).query)["data"][0]
        self.assertIn("(32.68546,", query)
        self.assertNotIn("area[", query)
        self.assertLessEqual(urlopen.call_args.kwargs["timeout"], 12)
        self.assertIn("[maxsize:33554432]", query)
        self.assertEqual(
            provider.search(industry="Restaurant", location="san diego, CA", limit=5),
            rows,
        )
        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(provider.summary["cached"])

    @patch("crm.lead_finder.request.urlopen")
    def test_provider_preserves_partial_results_and_explains_location_failure(
        self, urlopen
    ):
        urlopen.return_value.__enter__.return_value = self.response(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {"name": "Partial Cafe", "phone": "6195550100"},
                }
            ],
            remark="runtime timeout",
        )
        provider = OpenStreetMapProvider()
        self.assertEqual(
            len(
                provider.search(
                    industry="Restaurant", location="San Diego, CA", limit=5
                )
            ),
            1,
        )
        self.assertIn("time limit", provider.summary["warning"])
        cache.clear()
        calls = urlopen.call_count
        with self.assertRaises(DirectoryError) as caught:
            provider.search(industry="Restaurant", location="Misspelled, CA", limit=5)
        self.assertEqual(caught.exception.code, "location_not_found")
        self.assertEqual(urlopen.call_count, calls)

    @patch("crm.lead_finder.request.urlopen")
    def test_rate_limit_and_malformed_responses_are_actionable(self, urlopen):
        provider = OpenStreetMapProvider()
        urlopen.side_effect = HTTPError(
            "https://example.com", 429, "Too many", {}, None
        )
        with self.assertRaises(DirectoryError) as caught:
            provider.search(industry="Restaurant", location="San Diego, CA", limit=5)
        self.assertEqual(caught.exception.code, "rate_limited")
        with self.assertRaises(DirectoryError) as caught:
            provider.search(industry="Restaurant", location="San Diego, CA", limit=5)
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertEqual(urlopen.call_count, 2)
        cache.clear()
        urlopen.side_effect = None
        urlopen.return_value.__enter__.return_value = self.response(None)
        with self.assertRaises(DirectoryError) as caught:
            provider.search(industry="Restaurant", location="San Diego, CA", limit=5)
        self.assertEqual(caught.exception.code, "invalid_response")

    @override_settings(
        LEAD_FINDER_OVERPASS_URL="https://primary.example/api/interpreter",
        LEAD_FINDER_OVERPASS_FALLBACK_URL="https://backup.example/api/interpreter",
    )
    @patch("crm.lead_finder.request.urlopen")
    def test_timeout_uses_backup_and_preserves_source(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = self.response(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {"name": "Cafe", "website": "https://example.com"},
                }
            ]
        )
        urlopen.side_effect = [TimeoutError(), response]
        provider = OpenStreetMapProvider()
        self.assertEqual(
            len(
                provider.search(
                    industry="Restaurant", location="San Diego, CA", limit=5
                )
            ),
            1,
        )
        self.assertTrue(provider.summary["failover"])
        self.assertEqual(provider.summary["host"], "backup.example")
        self.assertEqual(urlopen.call_count, 2)
        cache.clear()
        urlopen.side_effect = TimeoutError()
        with self.assertRaises(DirectoryError) as caught:
            provider.search(industry="Restaurant", location="San Diego, CA", limit=5)
        self.assertEqual(caught.exception.code, "provider_timeout")
        self.assertEqual(urlopen.call_count, 4)

    def test_history_handles_deleted_employee_and_samples_are_excluded_everywhere(self):
        batch = self.batch(
            status="completed", provider_summary={"fallback_directory": 5}
        )
        LeadStaging.objects.create(
            batch=batch,
            created_by=self.rep,
            business_name="Generated sample sentinel",
            industry="Restaurant",
            phone_number="5551234567",
        )
        self.client.force_login(self.owner)
        batch.employee = None
        batch.save()
        response = self.client.get(reverse("lead_generation_history"))
        self.assertContains(response, "Unassigned")
        self.assertContains(response, "Legacy sample")
        for url in [
            reverse("lead_finder"),
            reverse("lead_generation_batch_detail", args=[batch.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Generated sample sentinel")
        sheet = self.client.get(
            reverse("lead_sheet_export"), {"source": "finder", "kind": "prospects"}
        )
        self.assertEqual(sheet.status_code, 200)

    @patch("crm.views.advance_lead_generation_batch")
    def test_create_returns_results_page_then_execution_is_scoped_and_post_only(
        self, generate
    ):
        data = {"industry": "Restaurant", "location": "San Diego CA", "quantity": "5"}
        first = self.client.post(reverse("lead_finder"), data)
        second = self.client.post(reverse("lead_finder"), data)
        self.assertEqual(LeadGenerationBatch.objects.count(), 1)
        self.assertEqual(first.url, second.url)
        generate.assert_not_called()
        batch = LeadGenerationBatch.objects.get()
        self.assertContains(self.client.get(first.url), "data-finder-run")
        run_url = reverse("lead_generation_batch_run", args=[batch.pk])
        self.assertEqual(self.client.get(run_url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(run_url).status_code, 404)
        self.client.force_login(self.rep)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.rep)
        self.assertEqual(secured.post(run_url).status_code, 403)
        self.assertEqual(
            self.client.post(run_url, HTTP_ACCEPT="application/json").status_code, 200
        )
        generate.assert_called_once_with(batch.pk)
        batch.status = "completed"
        batch.save()
        self.client.post(run_url, HTTP_ACCEPT="application/json")
        generate.assert_called_once()

    def test_blank_phone_does_not_duplicate_unrelated_leads_and_public_email_is_saved(
        self,
    ):
        Lead.objects.create(
            business_name="Unrelated record", phone="", city="San Diego", state="CA"
        )
        provider = MagicMock(name="provider")
        provider.name = "openstreetmap"
        provider.summary = {}
        provider.search.return_value = [
            DirectoryLead(
                business_name="Cafe One",
                phone_number="",
                industry="Restaurant",
                website="https://example.com",
                email="hello@example.com",
                city="San Diego",
                state="CA",
                source_url="https://www.openstreetmap.org/node/1",
            )
        ]
        batch = generate_leads_for_batch(self.batch().pk, providers=[provider])
        self.assertEqual(batch.quantity_generated, 1)
        row = batch.staged_leads.get()
        lead = convert_staging_to_crm_lead(row, employee=self.rep, contacted=False)
        self.assertEqual(lead.email, "hello@example.com")
        self.assertEqual(lead.duplicate_key, "biz:cafeone:sandiegoca")
        self.assertIsNone(lead.last_contact_at)
        repeat = generate_leads_for_batch(self.batch().pk, providers=[provider])
        self.assertEqual(repeat.quantity_generated, 0)
        self.assertEqual(repeat.duplicates_removed, 1)
        self.assertIn("already in the CRM", repeat.status_message)

    @patch("crm.lead_finder.request.urlopen")
    def test_stale_batches_resume_instead_of_discarding_the_search(self, urlopen):
        urlopen.return_value.__enter__.return_value = self.response([])
        batch = self.batch(status="searching", started_at=timezone.now() - timedelta(minutes=4))
        self.assertTrue(batch.is_stalled)
        status = self.client.get(reverse("lead_generation_batch_status", args=[batch.pk])).json()["batch"]
        self.assertTrue(status["is_open"])
        self.assertTrue(status["can_advance"])
        self.assertContains(self.client.get(reverse("lead_generation_batch_detail", args=[batch.pk])), "Ready to resume")
        self.assertEqual(self.client.post(reverse("lead_generation_batch_run", args=[batch.pk])).status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "completed")

    def test_separate_branches_with_different_phones_are_not_false_duplicates(self):
        Lead.objects.create(
            business_name="Neighborhood Cafe",
            phone="6195550100",
            city="San Diego",
            state="CA",
        )
        provider = MagicMock()
        provider.name = "openstreetmap"
        provider.summary = {}
        provider.search.return_value = [
            DirectoryLead(
                business_name="Neighborhood Cafe",
                phone_number="6195550101",
                city="San Diego",
                state="CA",
                industry="Restaurant",
            )
        ]
        batch = generate_leads_for_batch(self.batch().pk, providers=[provider])
        self.assertEqual(batch.quantity_generated, 1)
        self.assertEqual(batch.duplicates_removed, 0)

    @override_settings(LEAD_FINDER_ENABLE_PUBLIC_HTTP=False)
    def test_disabled_search_does_not_create_batches(self):
        response = self.client.post(
            reverse("lead_finder"),
            {"industry": "Restaurant", "location": "San Diego, CA", "quantity": "5"},
        )
        self.assertContains(response, "Public search is disabled")
        self.assertFalse(LeadGenerationBatch.objects.exists())

    def test_dropdown_locations_validate_state_membership_and_history_links(self):
        from .directory_locations import city_choices, US_STATES
        for state in US_STATES:
            for value, _ in city_choices(state):
                with self.subTest(state=state, city=value):
                    self.assertEqual(resolve_city(f"{value}, {state}")[:2], (value, state))
        self.assertIn(("Miami", "Miami"), city_choices("FL"))
        valid = LeadFinderForm({"industry": "Insurance", "state": "FL", "city": "Miami", "quantity": "5"})
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.cleaned_data["location"], "Miami, FL")
        for state, city in [("FL", "San Diego"), ("XX", "Miami"), ("", "Miami"), ("FL", "")]:
            form = LeadFinderForm({"industry": "Insurance", "state": state, "city": city,
                                   "location": "Miami, FL", "quantity": "5"})
            self.assertFalse(form.is_valid())  # Legacy hidden field cannot bypass a bad pair.
        retry = LeadFinderForm(initial={"location": "Miami Florida"})
        self.assertEqual(retry["city"].value(), "Miami")
        self.assertEqual(retry["state"].value(), "FL")
        self.assertEqual(resolve_city("Ft. Lauderdale FL")[:2], ("Fort Lauderdale", "FL"))
        response = self.client.get(reverse("lead_finder_cities"), {"state": "fl"})
        self.assertEqual(response.json()["state"], "FL")
        self.assertIn({"value": "Miami", "label": "Miami"}, response.json()["cities"])
        self.assertEqual(self.client.get(reverse("lead_finder_cities"), {"state": "invalid"}).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("lead_finder_cities"), {"state": "FL"}).status_code, 302)

    @override_settings(LEAD_FINDER_OVERPASS_URL="https://primary.example/api/interpreter",
                       LEAD_FINDER_OVERPASS_FALLBACK_URL="https://backup.example/api/interpreter")
    @patch("crm.lead_finder.request.urlopen")
    def test_each_browser_step_has_one_attempt_then_resumes_backup_and_saving(self, urlopen):
        from .lead_finder import advance_lead_generation_batch
        response = MagicMock()
        response.__enter__.return_value = self.response([
            {"type": "node", "id": 99, "tags": {"name": "Miami Insurance", "website": "https://example.com"}}
        ])
        urlopen.side_effect = [HTTPError("https://primary.example", 429, "busy", {}, None), response]
        batch = self.batch()
        first = advance_lead_generation_batch(batch.pk)
        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(first.can_advance)
        self.assertEqual(first.search_state["provider_index"], 1)
        # Simulate a new HTTP request / fresh provider objects after a refresh.
        second = advance_lead_generation_batch(batch.pk)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(second.status, "saving")
        self.assertEqual(second.staged_leads.count(), 0)
        third = advance_lead_generation_batch(batch.pk)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(third.status, "completed")
        self.assertEqual(third.quantity_generated, 1)
        self.assertTrue(third.provider_summary["directory"]["failover"])
        self.assertEqual(third.search_state, {})

    def test_active_lease_blocks_overlapping_tabs_and_stale_response_is_discarded(self):
        from .lead_finder import advance_lead_generation_batch
        batch = self.batch()
        primary = MagicMock()
        primary.name = "fixture"
        primary.summary = {}
        replacement = MagicMock()
        replacement.name = "fixture"
        replacement.summary = {}
        replacement.search.return_value = [DirectoryLead(business_name="New worker", phone_number="3055550123", industry="Insurance")]
        def slow_response(**kwargs):
            occupied = advance_lead_generation_batch(batch.pk, providers=[replacement])
            self.assertFalse(occupied.can_advance)
            replacement.search.assert_not_called()
            LeadGenerationBatch.objects.filter(pk=batch.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            advance_lead_generation_batch(batch.pk, providers=[replacement])
            return [DirectoryLead(business_name="Stale worker", phone_number="3055550199", industry="Insurance")]
        primary.search.side_effect = slow_response
        result = advance_lead_generation_batch(batch.pk, providers=[primary])
        self.assertEqual(result.status, "saving")
        self.assertEqual(result.search_state["candidates"][0]["business_name"], "New worker")
        finished = advance_lead_generation_batch(batch.pk, providers=[replacement])
        self.assertEqual(finished.staged_leads.get().business_name, "New worker")
        self.assertFalse(LeadStaging.objects.filter(business_name="Stale worker").exists())

    def test_many_duplicates_are_checkpointed_and_later_fresh_candidates_are_saved(self):
        from .lead_finder import advance_lead_generation_batch
        rows = [DirectoryLead(business_name=f"Insurance {i}", phone_number=f"305555{i:04}", industry="Insurance") for i in range(106)]
        Lead.objects.bulk_create([Lead(business_name=r.business_name, phone=r.phone_number,
                                      duplicate_key="phone:" + r.phone_number) for r in rows[:105]])
        provider = MagicMock()
        provider.name = "fixture"
        provider.summary = {}
        provider.search.return_value = rows
        batch = self.batch()
        first = advance_lead_generation_batch(batch.pk, providers=[provider])
        self.assertEqual(first.status, "saving")
        checkpoint = advance_lead_generation_batch(batch.pk, providers=[provider])
        self.assertEqual(checkpoint.search_state["offset"], 100)
        self.assertEqual(checkpoint.duplicates_removed, 100)
        finished = advance_lead_generation_batch(batch.pk, providers=[provider])
        self.assertEqual(finished.status, "completed")
        self.assertEqual(finished.quantity_generated, 1)
        self.assertEqual(finished.duplicates_removed, 105)
        self.assertEqual(finished.staged_leads.get().business_name, "Insurance 105")
        self.assertEqual(provider.search.call_count, 1)
        advance_lead_generation_batch(batch.pk, providers=[provider])
        self.assertEqual(finished.staged_leads.count(), 1)

    @patch("crm.lead_finder.request.urlopen")
    def test_insurance_aliases_and_cache_keep_candidates_beyond_requested_count(self, urlopen):
        urlopen.return_value.__enter__.return_value = self.response([
            {"type": "node", "id": i, "tags": {"name": f"Insurance {i}", "website": f"https://example.com/{i}"}} for i in range(30)
        ])
        provider = OpenStreetMapProvider()
        rows = provider.search(industry="Insurance", location="Miami FL", limit=5)
        query = parse_qs(urlsplit(urlopen.call_args.args[0].full_url).query)["data"][0]
        self.assertIn('["shop"="insurance"]', query)
        self.assertIn('["office"="insurance"]', query)
        self.assertIn('(25.63024,', query)
        self.assertEqual(len(rows), 30)
        second = provider.search(industry="insurance agents", location="Miami Florida", limit=20)
        self.assertEqual(len(second), 30)
        self.assertEqual(urlopen.call_count, 1)

    def test_directory_failure_is_not_recorded_as_zero_results(self):
        provider = MagicMock()
        provider.name = "fixture"
        provider.search.side_effect = DirectoryError("The directory is busy. Try again shortly.", "provider_timeout")
        failed = generate_leads_for_batch(self.batch().pk, providers=[provider])
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.provider_summary["error_code"], "provider_timeout")
        self.assertNotIn("no usable", failed.status_message)

    @override_settings(CELERY_BROKER_URL="redis://example.invalid/0")
    @patch("crm.tasks.process_lead_generation_batch.delay")
    def test_fast_background_completion_survives_queue_metadata_update(self, delay):
        from .lead_finder import enqueue_generation_batch
        batch = self.batch(quantity_generated=2)
        def finish_before_return(batch_id):
            LeadGenerationBatch.objects.filter(pk=batch_id).update(
                status="completed", status_message="Found 2 new businesses.",
                provider_summary={"directory": {"listings_checked": 2}})
            return MagicMock(id="fixture-task")
        delay.side_effect = finish_before_return
        self.assertTrue(enqueue_generation_batch(batch))
        batch.refresh_from_db()
        self.assertEqual(batch.status_message, "Found 2 new businesses.")
        self.assertEqual(batch.provider_summary["directory"]["listings_checked"], 2)
        self.assertEqual(batch.provider_summary["celery_task_id"], "fixture-task")

    def test_ambiguous_city_choices_keep_distinct_coordinates(self):
        from .directory_locations import city_choices
        choices = [name for name, _ in city_choices("CA") if name.startswith("Alta Sierra")]
        self.assertEqual(len(choices), 2)
        self.assertEqual(len({resolve_city(name + ", CA")[2:] for name in choices}), 2)
        self.assertTrue(all("near" in name for name in choices))
