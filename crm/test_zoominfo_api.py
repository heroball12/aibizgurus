import json
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone

from . import zoominfo_api as api
from .importers import import_lead_file, parse_lead_file
from .models import Company, CompanyIntentSignal, Lead, LeadActivity, LeadUploadPreview, ZoomInfoSearch
from .zoominfo_forms import SearchForm


def contact_resource(person_id="1001", name="Alex", *, dnc=False):
    return {"id": person_id, "type": "Contact", "attributes": {
        "firstName": name, "lastName": "Rivera", "jobTitle": "President", "email": name.lower() + "@example.test",
        "phone": "+1 (760) 555-0101", "directPhoneDoNotCall": dnc, "hasEmail": True, "hasDirectPhone": True,
        "company": {"id": "2001", "name": "Example Motors", "website": "example.test", "city": "Doral", "state": "Florida", "revenueNumeric": 2054000},
        "futureField": {"key": "Preserve me"}}, "meta": {"matchStatus": "FULL_MATCH", "input": {"personId": person_id}}}


def person_row():
    item = contact_resource()
    return {"id": item["id"], "company_id": "2001", "company": "Example Motors", "name": "Alex Rivera", "title": "President", "website": "https://example.test", "has_email": True, "raw": item}


def intent_resource(**changes):
    attrs = {"company": {"id": "2001", "name": "Example Motors", "website": "example.test"},
             "topic": "Artificial Intelligence", "category": "Technology", "signalDate": timezone.now().isoformat(),
             "signalScore": 87, "audienceStrength": "B", "spikesInDateRange": 3}
    attrs.update(changes)
    return {"id": "signal#2001#today", "type": "Intent", "attributes": attrs}


_intent_search = api.intent_search


def signal_row(**changes):
    with patch.object(api, "call", return_value={"data": [intent_resource(**changes)]}):
        return _intent_search({"topics": ["Artificial Intelligence"]})[0][0]


def response(payload=None, status=200):
    result = Mock(status_code=status, headers={})
    result.content = json.dumps(payload or {}).encode()
    result.json.return_value = payload or {}
    return result


@override_settings(ZOOMINFO_CLIENT_ID="fictional-id", ZOOMINFO_CLIENT_SECRET="fictional-secret", ZOOMINFO_ENABLED=True)
class AdapterTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("crm.zoominfo_api.requests.request")
    def test_oauth_cached_separate_scopes_and_credentials_not_in_url(self, http):
        http.return_value = response({"access_token": "private-test-token", "expires_in": 3600})
        api.token(); api.token()
        self.assertEqual(http.call_count, 1)
        kwargs = http.call_args.kwargs
        self.assertEqual(kwargs["auth"], ("fictional-id", "fictional-secret"))
        self.assertEqual(kwargs["data"]["scope"], api.SCOPES)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (3, 12))
        api.token(intent=True)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(http.call_args.kwargs["data"]["scope"], api.INTENT_SCOPES)
        with override_settings(ZOOMINFO_CLIENT_SECRET="rotated-secret"):
            api.token()
        self.assertEqual(http.call_count, 3)

    @patch("crm.zoominfo_api.requests.request")
    def test_only_explicit_401_refreshes_and_retries_once(self, http):
        http.side_effect = [response({"access_token":"one", "expires_in":1000}), response(status=401),
                            response({"access_token":"two", "expires_in":1000}), response({"data":[]})]
        self.assertEqual(api.call("POST", "/data/v1/contacts/enrich", paid=True), {"data":[]})
        self.assertEqual(http.call_count, 4)
        self.assertEqual(http.call_args.kwargs["headers"]["Authorization"], "Bearer two")

    @patch("crm.zoominfo_api.requests.request")
    def test_timeout_uncertain_only_for_chargeable_request(self, http):
        http.side_effect = requests.Timeout("secret provider details")
        for paid in (False,True):
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api._request("POST", "/data/v1/contacts/enrich", paid=paid)
            self.assertEqual(ctx.exception.uncertain, paid)
            self.assertNotIn("secret", str(ctx.exception))

    @patch("crm.zoominfo_api.requests.request")
    def test_403_429_5xx_and_redirects_are_sanitized_without_retry(self, http):
        for status in (403,429,503,302):
            http.return_value = response({"debug":"sensitive-provider-body"}, status)
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api._request("POST", "/data/v1/contacts/enrich", paid=True)
            self.assertNotIn("sensitive", str(ctx.exception))
            self.assertNotIn("sensitive", json.dumps(ctx.exception.diagnostic))
            self.assertEqual(ctx.exception.uncertain, status in (503,302))
        self.assertEqual(http.call_count,4)

    @patch("crm.zoominfo_api.requests.request")
    def test_provider_diagnostics_keep_error_code_field_and_reference(self, http):
        http.return_value = response({"errors": [{"code": "INVALID_FILTER", "id": "err-abc-123",
            "title": "Validation failed", "detail": "Minimum score must be between 60 and 100.",
            "source": {"pointer": "/data/attributes/signalScoreMin"}}]}, 422)
        http.return_value.headers = {"X-Request-ID": "req-abc-123"}
        with self.assertRaises(api.ZoomInfoError) as ctx:
            api._request("POST", "/data/v1/intent/search")
        diagnostic = ctx.exception.diagnostic
        self.assertEqual(diagnostic["status"], 422)
        self.assertEqual(diagnostic["operation"], "Intent search")
        self.assertEqual(diagnostic["reference"], "req-abc-123")
        issue = diagnostic["provider_errors"][0]
        self.assertEqual(issue["code"], "INVALID_FILTER")
        self.assertEqual(issue["reference"], "err-abc-123")
        self.assertEqual(issue["field"], "/data/attributes/signalScoreMin")
        self.assertIn("60 and 100", issue["detail"])

    @patch("crm.zoominfo_api.requests.request")
    def test_provider_messages_redact_credentials_and_echoed_prospect_data(self, http):
        detail = ("fictional-id fictional-secret Bearer private-token "
                  "client_secret=unexpected-secret person@example.test +1 (760) 555-0101 "
                  "https://private.test/path?token=abc Example Motors")
        http.return_value = response({"errors": [{"code": "DENIED", "detail": detail}],
                                      "debug": "do not show raw body"}, 403)
        with self.assertRaises(api.ZoomInfoError) as ctx:
            api._request("POST", "/data/v1/companies/search", headers={"Authorization": "Bearer private-token"},
                         json={"data": {"attributes": {"companyName": "Example Motors"}}})
        shown = json.dumps(ctx.exception.diagnostic)
        for private in ("fictional-id", "fictional-secret", "private-token", "unexpected-secret", "person@example.test",
                        "760", "private.test", "Example Motors", "do not show raw body"):
            self.assertNotIn(private, shown)
        self.assertIn("DENIED", shown)
        self.assertIn("redacted", shown)

    @patch("crm.zoominfo_api.requests.request")
    def test_oauth_error_explains_scope_rejection_and_not_missing_credentials(self, http):
        http.return_value = response({"error": "invalid_scope", "error_description": "Requested scopes are not allowed for this app."}, 400)
        with self.assertRaises(api.ZoomInfoError) as ctx:
            api.token(intent=True)
        self.assertEqual(ctx.exception.diagnostic["operation"], "Authentication")
        self.assertEqual(ctx.exception.diagnostic["provider_errors"][0]["code"], "invalid_scope")
        self.assertIn("required API scopes", ctx.exception.diagnostic["next_step"])
        self.assertEqual(http.call_count, 1)

    @patch("crm.zoominfo_api.requests.request")
    def test_intent_preserves_actual_403_and_does_not_claim_missing_sku(self, http):
        http.side_effect = [response({"access_token": "test-token", "expires_in": 1000}),
                            response({"errors": [{"code": "NOT_AUTHORIZED", "detail": "Delegated user lacks access."}]}, 403)]
        with self.assertRaises(api.ZoomInfoError) as ctx:
            api.intent_search({"topics": ["AI"]})
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.diagnostic["provider_errors"][0]["code"], "NOT_AUTHORIZED")
        self.assertIn("does not prove", ctx.exception.diagnostic["next_step"])
        self.assertEqual(http.call_count, 2)

    @patch("crm.zoominfo_api.requests.request")
    def test_unreadable_and_oversized_errors_still_show_http_status(self, http):
        cases = [response(["not an error object"], 503), response(status=502), response(status=403)]
        cases[1].json.side_effect = ValueError("private html response")
        cases[2].content = b"x" * 64_001
        for result in cases:
            http.return_value = result
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api._request("GET", "/data/v1/lookup/intent-topics")
            self.assertEqual(ctx.exception.status, result.status_code)
            self.assertEqual(ctx.exception.diagnostic["provider_errors"], [])
        cases[2].json.assert_not_called()

    @patch("crm.zoominfo_api.requests.request")
    def test_rate_limit_wait_and_network_failure_are_distinct(self, http):
        http.return_value = response({"errors": [{"code": "QUOTA_EXCEEDED", "detail": "Monthly allowance exhausted."}]}, 429)
        http.return_value.headers = {"Retry-After": "90"}
        with self.assertRaises(api.ZoomInfoError) as ctx:
            api._request("GET", "/data/v1/lookup/enrich")
        self.assertEqual(ctx.exception.diagnostic["retry_after"], 90)
        self.assertIn("allowance exhausted", ctx.exception.diagnostic["provider_errors"][0]["detail"])
        for failure, message in [(requests.ConnectionError("private hostname"), "could not communicate"),
                                 (requests.exceptions.SSLError("private certificate"), "secure connection"),
                                 (requests.Timeout("private request"), "timed out")]:
            http.side_effect = failure
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api._request("GET", "/data/v1/lookup/enrich")
            self.assertIn(message, str(ctx.exception))
            self.assertNotIn("private", json.dumps(ctx.exception.diagnostic))
            self.assertIsNone(ctx.exception.status)

    @patch("crm.zoominfo_api.requests.request")
    def test_local_configuration_reports_exact_missing_setting_without_network(self, http):
        with override_settings(ZOOMINFO_CLIENT_SECRET=""):
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api.token()
            self.assertIn("ZOOMINFO_CLIENT_SECRET", str(ctx.exception))
            self.assertNotIn("ZOOMINFO_CLIENT_ID", str(ctx.exception))
        with override_settings(ZOOMINFO_ENABLED=False):
            with self.assertRaises(api.ZoomInfoError) as ctx:
                api.token()
            self.assertIn("disabled", str(ctx.exception))
        http.assert_not_called()

    @patch("crm.zoominfo_api.call")
    def test_search_and_enrich_contract(self, call):
        call.return_value = {"data":[contact_resource()],"meta":{"totalResults":29}}
        rows,total,more = api.search("people", {"companyId":"2001"}, 1)
        self.assertEqual((rows[0]["id"],total,more),("1001",29,True))
        self.assertNotIn("email", rows[0])
        self.assertEqual(call.call_args.args,("POST","/data/v1/contacts/search"))
        self.assertEqual(call.call_args.kwargs["json"]["data"]["type"],"ContactSearch")
        api.enrich(["1001"],["id","email"])
        self.assertTrue(call.call_args.kwargs["paid"])
        self.assertEqual(call.call_args.kwargs["json"]["data"]["attributes"]["matchPersonInput"],[{"personId":1001}])

    @patch("crm.zoominfo_api.call")
    def test_intent_contract_does_not_infer_company_from_recommended_people(self, call):
        item = intent_resource(company=None, recommendedContacts=[{"id":"1001","companyName":"Not reliable"}])
        call.return_value = {"data":[item]}
        rows,_,_ = api.intent_search({"topics":["Artificial Intelligence"]})
        self.assertFalse(rows[0]["saveable"])
        self.assertEqual(rows[0]["company_id"],"")
        self.assertEqual(call.call_args.args,("POST","/data/v1/intent/search"))
        self.assertTrue(call.call_args.kwargs["intent"])
        self.assertEqual(call.call_args.kwargs["params"]["sort"],"-signalDate")

    @patch("crm.zoominfo_api.call")
    def test_intent_bad_date_score_and_url_cannot_attach(self, call):
        call.return_value = {"data":[intent_resource(signalDate="bad",signalScore=999,company={"id":"2001","website":"javascript:alert(1)"})]}
        row = api.intent_search({"topics":["AI"]})[0][0]
        self.assertFalse(row["saveable"])
        self.assertEqual(row["website"],"")
        self.assertIsNone(row["score"])

    @patch("crm.zoominfo_api.call")
    def test_topic_lookup_is_cached_with_real_values(self, call):
        call.return_value = {"data":[{"id":"AI","type":"IntentTopic","attributes":{"name":"Artificial Intelligence","category":"Technology"}}]}
        self.assertEqual(api.intent_topics(),[])
        self.assertEqual(api.intent_topics(fetch=True),[("Artificial Intelligence","Technology")])
        api.intent_topics(fetch=True)
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args,("GET","/data/v1/lookup/intent-topics"))

    @patch("crm.zoominfo_api.call")
    def test_field_lookup_restricts_known_schema_fields(self, call):
        call.return_value={"data":[{"attributes":{"fieldName":name, "accessGranted":allowed}} for name,allowed in [("id",True),("email",False),("unknown",True),("phone",True)]]}
        self.assertEqual(api.output_fields(),["id","phone"])

    def test_preview_preserves_raw_dnc_and_revenue_units(self):
        selected = person_row(); selected["raw"]["attributes"]["directPhoneDoNotCall"] = True
        payload={"data":[contact_resource()]}
        data,skipped = api.preview_csv(payload,[selected])
        self.assertEqual(skipped,0)
        parsed = parse_lead_file(SimpleUploadedFile("zi.csv",data))
        self.assertEqual(parsed.errors,[])
        row=parsed.rows[0]
        self.assertEqual(row.data["status"],"do_not_contact")
        self.assertEqual(row.raw["Company Revenue (USD)"],"2054000")
        self.assertEqual(row.data["value"],0)
        self.assertEqual(json.loads(row.raw["ZoomInfo API contact response"]),payload["data"][0])

    def test_mismatches_ambiguous_and_malformed_metadata_never_import(self):
        wrong=contact_resource("9999")
        ambiguous=contact_resource();ambiguous["meta"]["matchStatus"]="PARTIAL_MATCH"
        mismatched=contact_resource();mismatched["meta"]["input"]["personId"]="8888"
        malformed=contact_resource();malformed["meta"]=["bad"]
        data,skipped=api.preview_csv({"data":[wrong,ambiguous,mismatched,malformed]},[person_row()])
        self.assertEqual(data,b"");self.assertEqual(skipped,4)

    def test_form_builds_typed_schema_and_rejects_bad_filters(self):
        form=SearchForm({"state":"FL","zip_code":"33101","radius":"25","job_title":"Owner OR President","max_employees":"50"},kind="people")
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.criteria(),{"country":"United States","state":"Florida","zipCode":"33101","zipCodeRadiusMiles":25,"jobTitle":"Owner OR President","employeeRangeMax":"50","locationSearchType":"HQ"})
        self.assertFalse(SearchForm({},kind="companies").is_valid())
        self.assertFalse(SearchForm({"job_title":"Owner (Founder)"},kind="people").is_valid())
        self.assertFalse(SearchForm({"radius":"25"},kind="companies").is_valid())

    def test_intent_requires_catalog_topics_and_valid_dates(self):
        today=timezone.localdate().isoformat()
        valid={"topics":["AI"],"start_date":today,"end_date":today,"min_score":80}
        form=SearchForm(valid,kind="intent",topics=[("AI","Technology")])
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.criteria()["findRecommendedContacts"],False)
        self.assertNotIn("companyId",form.criteria())
        valid["topics"]=["Made up topic"]
        self.assertFalse(SearchForm(valid,kind="intent",topics=[("AI","")]).is_valid())

    def test_long_source_website_is_preserved_without_invalid_working_url(self):
        website = "https://example.test/" + "a" * 300
        row = signal_row(company={"id":"2001", "name":"Example Motors", "website":website})
        self.assertTrue(row["saveable"])
        self.assertEqual(row["website"], "")
        self.assertEqual(row["raw"]["attributes"]["company"]["website"], website)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", AI_SALES_INTELLIGENCE_ENABLED=False,
                   ZOOMINFO_CLIENT_ID="fictional-id", ZOOMINFO_CLIENT_SECRET="fictional-secret", ZOOMINFO_ENABLED=True)
class WorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        User=get_user_model()
        self.owner=User.objects.create_user(username="api-owner",role="owner")
        self.rep=User.objects.create_user(username="api-rep",role="employee")
        self.other=User.objects.create_user(username="api-other",role="employee")
        self.client.force_login(self.rep)

    def make_run(self,kind="people",**kwargs):
        return ZoomInfoSearch.objects.create(user=self.rep,kind=kind,results=[person_row()] if kind=="people" else [signal_row()],**kwargs)

    def details(self,run,**data):
        return self.client.post(reverse("zoominfo_details",args=[run.pk]),{"selected":["1001"],**data})

    @patch("crm.zoominfo_api.requests.request")
    def test_get_pages_never_purchase_or_search_and_render_cleanly(self,http):
        for kind in ("companies","people","intent"):
            res=self.client.get(reverse("zoominfo_workspace"),{"kind":kind})
            self.assertEqual(res.status_code,200)
        for kind in ("people","intent"):
            run=self.make_run(kind=kind)
            self.assertEqual(self.client.get(reverse("zoominfo_results",args=[run.pk])).status_code,200)
        http.assert_not_called()

    @patch("crm.zoominfo_api.search")
    def test_search_filters_chains_and_paginates_from_saved_criteria(self,search):
        search.return_value=([{"id":"2001","company":"McDonald's","website":"https://mcdonalds.com"},
                              {"id":"2002","company":"Example Motors","name":"Example Motors","website":"https://example.test"}],26,True)
        res=self.client.post(reverse("zoominfo_search"),{"kind":"companies","industry":"insurance","state":"FL","exclude_major_chains":"on"})
        self.assertEqual(res.status_code,302)
        run=ZoomInfoSearch.objects.get()
        self.assertEqual(run.hidden_chains,1); self.assertEqual(len(run.results),1)
        res=self.client.post(reverse("zoominfo_page",args=[run.pk]),{"page":2,"companyName":"tampered"})
        self.assertEqual(res.status_code,302)
        self.assertEqual(search.call_args.args[1],run.criteria)
        self.assertEqual(search.call_args.args[2],2)
        self.assertEqual(self.client.post(reverse("zoominfo_page",args=[run.pk]),{"page":99}).status_code,400)

    @patch("crm.zoominfo_api.output_fields",return_value=["id","email","companyName"])
    @patch("crm.zoominfo_api.enrich",return_value={"data":[contact_resource()]})
    def test_details_preview_confirm_and_double_click_use_one_paid_call(self,enrich,fields):
        run=self.make_run()
        res=self.details(run,assigned_to=self.other.pk)
        self.assertEqual(res.status_code,302)
        self.assertEqual(Lead.objects.count(),0)
        draft=LeadUploadPreview.objects.get()
        self.assertEqual(draft.assigned_to,self.rep)
        self.assertEqual(self.client.get(res.url).status_code,200)
        self.details(run)
        self.assertEqual(enrich.call_count,1)
        self.client.post(reverse("lead_import_confirm",args=[draft.pk]))
        lead=Lead.objects.get()
        self.assertEqual(lead.name,"Alex Rivera")
        self.assertEqual(lead.assigned_to,self.rep)
        self.assertEqual(lead.company.zoominfo_id,"2001")
        self.assertEqual(lead.company.source_data["Company Revenue (USD)"], "2054000")
        self.assertIn("ZoomInfo API company response", lead.company.source_data)
        self.assertEqual(lead.status,"new")
        self.details(run)
        self.assertEqual(enrich.call_count,1)
        self.assertEqual(Lead.objects.count(),1)

    @patch("crm.zoominfo_api.output_fields",return_value=["id"])
    @patch("crm.zoominfo_api.enrich",return_value={"data":[contact_resource()]})
    def test_expired_import_preview_reuses_received_details(self,enrich,fields):
        run=self.make_run()
        self.details(run)
        first=LeadUploadPreview.objects.get()
        LeadUploadPreview.objects.filter(pk=first.pk).update(created_at=timezone.now()-timedelta(hours=1))
        self.details(run)
        run.refresh_from_db()
        self.assertNotEqual(run.preview_id,first.pk)
        self.assertEqual(enrich.call_count,1)

    @patch("crm.zoominfo_api.output_fields",return_value=["id"])
    @patch("crm.zoominfo_api.enrich")
    def test_explicit_provider_rejection_allows_deliberate_retry(self,enrich,fields):
        run=self.make_run()
        enrich.side_effect=api.ZoomInfoError("Field access denied.", uncertain=False)
        self.details(run)
        run.refresh_from_db()
        self.assertEqual(run.state,"ready")
        self.assertEqual(run.error,"Field access denied.")
        enrich.side_effect=None
        enrich.return_value={"data":[contact_resource()]}
        self.details(run)
        self.assertEqual(enrich.call_count,2)

    @patch("crm.zoominfo_api.output_fields",return_value=["id"])
    @patch("crm.zoominfo_api.enrich",side_effect=api.ZoomInfoError("timeout",uncertain=True))
    def test_uncertain_request_is_not_retried(self,enrich,fields):
        run=self.make_run()
        self.details(run); self.details(run)
        run.refresh_from_db()
        self.assertEqual(run.state,"uncertain")
        self.assertEqual(enrich.call_count,1)
        self.assertFalse(LeadUploadPreview.objects.exists())

    @patch("crm.zoominfo_api.output_fields",return_value=["id"])
    @patch("crm.zoominfo_api.enrich",return_value={"data":"malformed"})
    def test_malformed_paid_response_is_retained_never_requested_again(self,enrich,fields):
        run=self.make_run()
        self.details(run); self.details(run)
        run.refresh_from_db()
        self.assertEqual(run.state,"complete")
        self.assertEqual(run.enrichment,{"data":"malformed"})
        self.assertEqual(enrich.call_count,1)

    @patch("crm.zoominfo_api.enrich")
    def test_forged_and_expired_selection_never_charged(self,enrich):
        run=self.make_run()
        self.client.post(reverse("zoominfo_details",args=[run.pk]),{"selected":["not-in-results"]})
        ZoomInfoSearch.objects.filter(pk=run.pk).update(created_at=timezone.now()-timedelta(days=2))
        self.details(run)
        enrich.assert_not_called()

    @patch("crm.zoominfo_api.enrich")
    def test_private_results_and_actions_cannot_be_used_by_other_staff(self,enrich):
        run=self.make_run()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("zoominfo_results",args=[run.pk])).status_code,404)
        self.assertEqual(self.details(run).status_code,404)
        enrich.assert_not_called()

    @patch("crm.zoominfo_api.enrich")
    def test_csrf_required_and_clients_cannot_use_tools(self,enrich):
        run=self.make_run()
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.rep)
        self.assertEqual(csrf.post(reverse("zoominfo_details",args=[run.pk]),{"selected":["1001"]}).status_code,403)
        customer=get_user_model().objects.create_user(username="zi-customer",role="client")
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse("zoominfo_workspace")).status_code,302)
        self.assertEqual(self.details(run).status_code,302)
        enrich.assert_not_called()

    @patch("crm.zoominfo_api.intent_topics",return_value=[("Artificial Intelligence","Technology")])
    @patch("crm.zoominfo_api.intent_search")
    def test_intent_search_and_save_preserve_dates_company_identity_and_metrics(self,search,topics):
        row=signal_row(); search.return_value=([row],1,False)
        today=timezone.localdate().isoformat()
        res=self.client.post(reverse("zoominfo_search"),{"kind":"intent","topics":["Artificial Intelligence"],"start_date":today,"end_date":today,"min_score":80,"state":"CA"})
        self.assertEqual(res.status_code,302)
        run=ZoomInfoSearch.objects.get()
        before=LeadActivity.objects.count()
        for _ in range(2):
            res=self.client.post(reverse("zoominfo_save_signal",args=[run.pk]),{"signal":row["id"],"score":100,"company_id":"999"})
            self.assertEqual(res.status_code,302)
        signal=CompanyIntentSignal.objects.get()
        self.assertEqual(signal.score,87);self.assertEqual(signal.zoominfo_company_id,"2001")
        self.assertEqual(signal.raw,row["raw"])
        self.assertEqual(signal.saved_by.count(),1)
        self.assertFalse(Lead.objects.exists());self.assertFalse(Company.objects.exists())
        self.assertEqual(LeadActivity.objects.count(),before)
        self.assertEqual(search.call_count,1)
        self.assertContains(self.client.get(reverse("intent_signals")),"Example Motors")

    def test_saved_signals_connect_to_later_import_and_respect_company_permissions(self):
        run=self.make_run(kind="intent")
        row=run.results[0]
        self.client.post(reverse("zoominfo_save_signal",args=[run.pk]),{"signal":row["id"]})
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("intent_signals")),"Example Motors")
        content,_=api.preview_csv({"data":[contact_resource()]},[person_row()])
        import_lead_file(SimpleUploadedFile("api.csv",content),uploaded_by=self.rep,default_assigned_to=self.rep)
        company=Company.objects.get()
        self.assertEqual(self.client.get(reverse("crm_company",args=[company.pk])).status_code,404)
        self.client.force_login(self.rep)
        self.assertContains(self.client.get(reverse("crm_company",args=[company.pk])),"Artificial Intelligence")
        self.assertContains(self.client.get(reverse("crm_companies"),{"intent":"recent"}),"Example Motors")
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("intent_signals")),"Example Motors")

    def test_shared_saved_signal_deduplicates_without_sharing_private_search(self):
        run=self.make_run(kind="intent");row=run.results[0]
        self.client.post(reverse("zoominfo_save_signal",args=[run.pk]),{"signal":row["id"]})
        other=ZoomInfoSearch.objects.create(user=self.other,kind="intent",results=run.results)
        self.client.force_login(self.other)
        self.client.post(reverse("zoominfo_save_signal",args=[other.pk]),{"signal":row["id"]})
        self.assertEqual(CompanyIntentSignal.objects.count(),1)
        self.assertEqual(CompanyIntentSignal.objects.get().saved_by.count(),2)

    def test_partial_signal_and_unselected_signal_cannot_be_saved(self):
        run=self.make_run(kind="intent");run.results[0]["saveable"]=False;run.save()
        self.assertEqual(self.client.post(reverse("zoominfo_save_signal",args=[run.pk]),{"signal":run.results[0]["id"]}).status_code,400)
        self.assertEqual(self.client.post(reverse("zoominfo_save_signal",args=[run.pk]),{"signal":"arbitrary"}).status_code,400)
        self.assertFalse(CompanyIntentSignal.objects.exists())

    @patch("crm.zoominfo_api.intent_search",side_effect=api.ZoomInfoError("Intent API access denied."))
    @patch("crm.zoominfo_api.intent_topics",return_value=[("AI","")])
    def test_intent_errors_preserve_filters_and_dont_report_zero_success(self,topics,search):
        today=timezone.localdate().isoformat()
        res=self.client.post(reverse("zoominfo_search"),{"kind":"intent","topics":["AI"],"start_date":today,"end_date":today,"min_score":80})
        self.assertContains(res,"Intent API access denied.")
        self.assertContains(res,'value="AI" selected')
        self.assertFalse(ZoomInfoSearch.objects.exists())

    @patch("crm.zoominfo_api.token")
    def test_connection_error_survives_redirect_and_escapes_provider_text(self, token):
        token.side_effect = api.ZoomInfoError("Authentication failed.", status=400, operation="Authentication",
            provider_errors=[{"code": "invalid_scope", "detail": "<script>alert(1)</script>"}],
            next_step="Check app scopes.", reference="req-test-123")
        self.client.force_login(self.owner)
        res = self.client.post(reverse("zoominfo_check"), follow=True)
        for text in ("Authentication failed.", "HTTP 400", "invalid_scope", "req-test-123", "Check app scopes."):
            self.assertContains(res, text)
        self.assertContains(res, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(res, "<script>alert(1)</script>")
        self.assertNotContains(res, "Start with the right business.")

    @patch("crm.zoominfo_api.search")
    def test_pagination_error_is_bound_to_its_private_search(self, search):
        search.side_effect = api.ZoomInfoError("Provider unavailable.", status=503, operation="People search")
        run = self.make_run(has_next=True)
        self.client.post(reverse("zoominfo_page", args=[run.pk]), {"page": 2})
        self.assertNotContains(self.client.get(reverse("zoominfo_workspace")), "Provider unavailable.")
        res = self.client.get(reverse("zoominfo_results", args=[run.pk]))
        self.assertContains(res, "Provider unavailable.")
        self.assertContains(res, "HTTP 503")
        self.assertContains(res, "earlier successful search")
        self.assertContains(res, "Example Motors")

    @patch("crm.zoominfo_api.output_fields", return_value=["id"])
    @patch("crm.zoominfo_api.enrich")
    def test_paid_diagnostics_persist_on_reload_and_clear_after_success(self, enrich, fields):
        run = self.make_run()
        error = api.ZoomInfoError("Contact fields denied.", status=403, operation="Contact details",
                                 provider_errors=[{"code": "FIELD_DENIED", "field": "/data/attributes/outputFields"}])
        enrich.side_effect = error
        self.details(run)
        run.refresh_from_db()
        self.assertEqual(run.error_details, error.diagnostic)
        for _ in range(2):
            res = self.client.get(reverse("zoominfo_results", args=[run.pk]))
            self.assertContains(res, "FIELD_DENIED")
            self.assertContains(res, "outputFields")
        enrich.side_effect = None
        enrich.return_value = {"data": [contact_resource()]}
        self.details(run)
        run.refresh_from_db()
        self.assertEqual(run.error_details, {})
        self.assertEqual(run.error, "")

    @patch("crm.zoominfo_api.output_fields", return_value=["id"])
    @patch("crm.zoominfo_api.enrich")
    def test_uncertain_diagnostic_never_encourages_paid_retry(self, enrich, fields):
        enrich.side_effect = api.ZoomInfoError("Request timed out.", uncertain=True, next_step="Try again later.")
        run = self.make_run()
        self.details(run)
        res = self.client.get(reverse("zoominfo_results", args=[run.pk]))
        self.assertContains(res, "Check usage before retrying.")
        self.assertNotContains(res, "Try again later.")
        self.details(run)
        self.assertEqual(enrich.call_count, 1)
