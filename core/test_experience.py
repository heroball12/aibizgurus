import json
import uuid
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core import signing
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from openai.types.chat import ChatCompletionMessage
from accounts.models import User
from clients.models import ClientAccount
from crm.models import Lead
from core.models import (DemoExperience, DemoRevision, DemoSession, DemoCRMLead, DemoCRMActivity,
                         DemoEvent, DemoFeedback, DemoRepAccess, DemoShareLink, DemoConversion, ConsultationRequest)
from core.experience import tools, engine, views
from core.experience.access import share_token, assessment_token
from core.experience.data import seed_content


def completion(content=None, calls=None):
    return ChatCompletionMessage(role="assistant", content=content,
        tool_calls=[{"id": "call_" + str(i), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(calls)] if calls else None)


class ExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_center", publish=True, stdout=StringIO())
        cls.exp = DemoExperience.objects.get(slug="automotive")
        cls.rep = User.objects.create_user(username="demo-rep", role="employee")
        cls.owner = User.objects.create_user(username="demo-owner", role="owner")
        cls.client_user = User.objects.create_user(username="demo-client", role="client")

    def start(self, client=None, **data):
        c = client or self.client
        response = c.post(reverse("experience_session"), json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return DemoSession.objects.get(pk=response.json()["id"])

    def action(self, session, action, client=None, **data):
        return (client or self.client).post(reverse("experience_action"), json.dumps({"session": str(session.pk), "action": action, **data}), content_type="application/json")

    def turn(self, session, message="Help me find an SUV", request_id=None, **data):
        return self.client.post(reverse("experience_turn"), json.dumps({"session": str(session.pk), "message": message, "request_id": request_id or str(uuid.uuid4()), **data}), content_type="application/json")

    def test_seed_is_idempotent_and_crm_isolation(self):
        original = self.exp.current_revision
        self.assertEqual(len(original.content["inventory"]), 60)
        self.assertEqual(len(original.content["scenarios"]), 10)
        counts = (Lead.objects.count(), ClientAccount.objects.count(), ConsultationRequest.objects.count())
        call_command("seed_demo_center", stdout=StringIO())
        self.assertEqual(DemoExperience.objects.count(), 1)
        self.assertEqual(DemoRevision.objects.count(), 1)
        self.assertEqual(counts, (Lead.objects.count(), ClientAccount.objects.count(), ConsultationRequest.objects.count()))
        self.exp.published = False
        self.exp.save()
        call_command("seed_demo_center", stdout=StringIO())
        self.exp.refresh_from_db()
        self.assertFalse(self.exp.published)

    def test_inventory_family_suv_filters_use_actual_prices(self):
        data = self.exp.current_revision.content
        result = tools.search_inventory(data, tools.Search(max_price=50000, min_seating=7, rows=3, drivetrain="AWD", body_style="SUV").model_dump())
        self.assertGreater(result["total"], 6)
        self.assertEqual(len(result["vehicles"]), 6)
        for v in result["vehicles"]:
            self.assertLessEqual(v["display_price"], 50000)
            self.assertGreaterEqual(v["seating"], 7)
            self.assertEqual(v["drivetrain"], "AWD")
        special = tools.search_inventory(data, tools.Search(query="VM-0101", max_price=43100).model_dump())
        self.assertEqual(special["vehicles"][0]["display_price"], 43100)

    def test_inventory_condition_fuel_query_status_and_sort(self):
        result = tools.search_inventory(self.exp.current_revision.content, tools.Search(condition="used", fuel_type="hybrid", max_price=35000, sort="mileage").model_dump())
        self.assertTrue(result["vehicles"])
        self.assertTrue(all(v["condition"] == "used" and v["fuel_type"] == "hybrid" for v in result["vehicles"]))
        empty = tools.search_inventory(self.exp.current_revision.content, tools.Search(max_price=1).model_dump())
        self.assertEqual(empty["total"], 0)
        sold = tools.search_inventory(self.exp.current_revision.content, tools.Search(status="sold").model_dump())
        self.assertEqual(sold["total"], 2)
        truck = tools.search_inventory(self.exp.current_revision.content, tools.Search(query="Ford F-150", condition="used").model_dump())
        self.assertEqual(truck["total"], 1)

    def test_unknown_vehicle_and_invalid_tool_schema_fail_closed(self):
        session = self.start()
        for name, args in [("get_vehicle", {"stock": "real-vin"}), ("search_inventory", {"max_price": "free"}), ("search_inventory", {"crm_id": 1}), ("delete_inventory", {}), ("get_vehicle", [])]:
            self.assertIn("error", tools.execute(session, name, args))
        self.assertEqual(Lead.objects.count(), 0)

    def test_compare_actual_vehicles_no_invented_stock(self):
        session = self.start()
        result = tools.execute(session, "compare_vehicles", {"stocks": ["VM-0101", "VM-0201"]})
        self.assertEqual(len(result["vehicles"]), 2)
        self.assertTrue(session.state["comparison"])
        self.assertIn("error", tools.execute(session, "compare_vehicles", {"stocks": ["VM-0101", "UNKNOWN"]}))
        self.assertIn("error", tools.execute(session, "compare_vehicles", {"stocks": ["VM-0101", "VM-0101"]}))

    def test_trade_does_not_value_or_require_unknown_details(self):
        s = self.start()
        result = tools.execute(s, "create_demo_trade_lead", {"year": 2022, "make": "Honda", "model": "Accord", "mileage": 60000})
        self.assertIsNone(result["valuation"])
        self.assertEqual(s.state["trade"]["mileage"], 60000)
        self.assertNotIn("trim", s.state["trade"])

    def test_sales_booking_requires_offered_valid_slot_and_available_vehicle(self):
        s = self.start()
        bad = {"slot_id": "invented", "stock": "VM-0101", "confirmed_by_customer": True}
        self.assertIn("error", tools.execute(s, "create_demo_sales_appointment", bad))
        slots = tools.execute(s, "get_available_sales_slots", {"day": "tomorrow"})["slots"]
        args = dict(bad, slot_id=slots[0]["id"])
        self.assertIn("error", tools.execute(s, "create_demo_sales_appointment", dict(args, confirmed_by_customer=False)))
        self.assertIn("error", tools.execute(s, "create_demo_sales_appointment", dict(args, stock="VM-1902")))
        result = tools.execute(s, "create_demo_sales_appointment", args)
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["confirmation"].startswith("DEMO-"))
        tools.sync_crm(s);s.save()
        self.assertEqual(DemoCRMLead.objects.get(session=s).stage, "appointment")
        self.assertEqual(DemoCRMActivity.objects.filter(lead__session=s, action="Demo appointment booked").count(), 1)
        tools.execute(s, "create_demo_sales_appointment", args);tools.sync_crm(s)
        self.assertEqual(DemoCRMActivity.objects.filter(lead__session=s, action="Demo appointment booked").count(), 1)
        self.assertFalse(Lead.objects.exists())

    def test_service_weekends_department_and_safety_context(self):
        s = self.start()
        self.assertEqual(tools.execute(s, "get_service_slots", {"day": "Sunday"})["slots"], [])
        saturday = tools.execute(s, "get_service_slots", {"day": "Saturday"})["slots"]
        self.assertEqual(len(saturday), 3)
        result = tools.execute(s, "create_demo_service_appointment", {"slot_id": saturday[0]["id"], "vehicle": "2021 Honda CR-V", "request": "Brakes and oil change", "confirmed_by_customer": True})
        self.assertEqual(result["department"], "service")
        self.assertIn("error", tools.execute(s, "create_demo_sales_appointment", {"slot_id": saturday[0]["id"], "stock": "VM-0101", "confirmed_by_customer": True}))
        policy = tools.execute(s, "get_business_info", {"topic": "service"})["service"]
        self.assertIn("Do not diagnose", policy)
        self.assertIn("stopping safely", policy)

    def test_after_hours_no_same_day_slots(self):
        self.client.force_login(self.rep)
        s = self.start(scenario="after-hours")
        self.assertEqual(tools.execute(s, "get_available_sales_slots", {"day": "today"})["slots"], [])
        self.assertEqual(len(tools.execute(s, "get_available_sales_slots", {"day": "tomorrow"})["slots"]), 3)
        self.assertIn("11:47 PM", engine.scenario_for(s)["context"])

    def test_reactivation_changes_interest_and_respects_stop(self):
        self.client.force_login(self.rep)
        s = self.start(scenario="reactivation")
        self.assertEqual(s.state["customer"]["name"], "Marcus")
        tools.execute(s, "update_customer", {"interest": "Three-row SUV"})
        self.assertEqual(s.state["customer"]["interest"], "Three-row SUV")
        tools.execute(s, "update_customer", {"market_status": "no_longer_in_market"})
        tools.execute(s, "create_demo_bdc_handoff", {"summary": "Already purchased", "recommended_follow_up": "Call tomorrow", "temperature": "qualified"})
        self.assertEqual(s.state["temperature"], "not_in_market")
        self.assertIn("No sales follow-up", s.state["follow_up"])
        slot = tools.execute(s, "get_available_sales_slots", {"day": "tomorrow"})["slots"][0]
        self.assertIn("error", tools.execute(s, "create_demo_sales_appointment", {"slot_id": slot["id"], "stock": "VM-0101", "confirmed_by_customer": True}))

    def test_knowledge_hours_spanish_finance_and_unknown(self):
        s = self.start()
        self.assertEqual(tools.execute(s, "get_department_hours", {"department": "service"})["hours"]["Sunday"], "Closed")
        self.assertIn("Spanish", json.dumps(tools.execute(s, "get_business_info", {"topic": "team"})))
        self.assertIn("No guaranteed approvals", tools.execute(s, "get_business_info", {"topic": "finance"})["finance"])
        self.assertEqual(tools.execute(s, "search_demo_faq", {"query": "unfindablezebraquux"})["faqs"], [])
        self.assertIn("only AI Specialists", tools.execute(s, "get_business_info", {"topic": "ai_business_gurus"})["ai_business_gurus"])

    def test_session_isolation_and_foreign_crm_denied(self):
        a = self.start();bclient = Client();b = self.start(bclient)
        a.state["customer"]["name"] = "Dealer A visitor";a.save()
        self.assertEqual(self.action(a, "handoff", bclient).status_code, 404)
        self.assertEqual(bclient.get(reverse("experience_crm"), {"session": a.pk}).status_code, 404)
        self.assertEqual(b.state["customer"]["name"], "Demo Customer")
        self.assertEqual(self.action(a, "inventory").status_code, 200)
        self.assertEqual(self.client.post(reverse("experience_action"), json.dumps({"session":"not-a-uuid","action":"handoff"}),content_type="application/json").status_code,404)

    def test_reset_clears_only_own_session_and_crm(self):
        a = self.start();b = self.start()
        for s in (a,b):
            tools.execute(s, "update_customer", {"interest": "SUV"});tools.sync_crm(s);s.transcript=[{"role":"user","content":"Example"}];s.save()
        response = self.action(a, "reset")
        self.assertEqual(response.status_code, 200)
        a.refresh_from_db();b.refresh_from_db()
        self.assertEqual((a.state,a.transcript,a.protocol),({},[],[]))
        self.assertFalse(DemoCRMLead.objects.filter(session=a).exists())
        self.assertTrue(DemoCRMLead.objects.filter(session=b).exists())
        self.assertTrue(b.transcript)
        self.assertIsNone(b.ended_at)
        self.assertEqual(self.action(a, "handoff").status_code,404)

    def test_public_cannot_select_staff_scenario_or_feedback(self):
        s = self.start(scenario="reactivation")
        self.assertEqual(s.scenario,"vehicle-shopping")
        self.assertEqual(self.action(s,"feedback",category="ui",notes="test").status_code,403)
        self.assertRedirects(self.client.get(reverse("experience_manage")),reverse("login")+"?next="+reverse("experience_manage"))
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("experience_manage")).status_code,404)
        self.assertEqual(self.client.get(reverse("experience_guide")).status_code,404)

    def test_rep_controls_access_and_revocation(self):
        self.client.force_login(self.rep)
        self.assertContains(self.client.get(reverse("experience_home")), "Demo controls")
        s=self.start(scenario="service")
        self.assertEqual(s.scenario,"service")
        self.assertEqual(s.rep,self.rep)
        self.assertEqual(self.action(s,"feedback",category="slow",notes="Slow turn").status_code,200)
        self.assertEqual(DemoFeedback.objects.get().session,s)
        self.assertEqual(self.client.get(reverse("experience_manage")).status_code,404)
        DemoRepAccess.objects.create(user=self.rep,enabled=False)
        self.assertNotContains(self.client.get(reverse("experience_home")),"id=\"demoControls\"")
        self.assertEqual(self.client.get(reverse("experience_guide")).status_code,404)

    def test_unpublished_demo_is_not_public_including_existing_sessions(self):
        s=self.start();self.exp.published=False;self.exp.save()
        self.assertEqual(self.client.get(reverse("experience_home")).status_code,404)
        self.assertEqual(self.action(s,"handoff").status_code,404)
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse("experience_home")).status_code,200)

    def test_share_preserves_rep_scenario_not_customer(self):
        self.client.force_login(self.rep);s=self.start(scenario="after-hours")
        s.state["customer"]["name"]="Never share this";s.save()
        response=self.action(s,"share").json();token=response["url"].split("?ref=")[1]
        other=Client();new=self.start(other,ref=token)
        self.assertEqual((new.rep,new.scenario,new.source),(self.rep,"after-hours","share"))
        self.assertEqual(new.state["customer"]["name"],"Demo Customer")
        self.assertEqual(new.transcript,[])
        invalid=self.start(other,ref=token+'bad')
        self.assertIsNone(invalid.rep)
        self.assertEqual(invalid.scenario,"vehicle-shopping")

    def test_qr_and_manifest_and_public_pages(self):
        s=self.start()
        self.assertEqual(self.client.get(reverse("experience_qr"),{"session":s.pk})["Content-Type"],"image/svg+xml")
        self.assertEqual(self.client.get(reverse("experience_manifest")).json()["display"],"standalone")
        self.assertContains(self.client.get(reverse("demo")),"Enter Velocity Motors")
        self.assertContains(self.client.get(reverse("experience_home")),"Synthetic" if False else "synthetic")
        self.assertContains(self.client.get(reverse("experience_crm"),{"session":s.pk}),"simulated staff sign-in")

    def test_demo_crm_login_records_updates_and_preserves_human_notes(self):
        s=self.start();tools.execute(s,"update_customer",{"name":"Taylor Demo","interest":"SUV"});tools.sync_crm(s);s.save()
        url=reverse("experience_crm")+'?session='+str(s.pk)
        self.assertEqual(self.client.get(reverse("experience_crm_state"),{"session":s.pk}).status_code,403)
        self.client.post(url,{"action":"signin"})
        self.assertContains(self.client.get(url),"Taylor Demo")
        self.client.post(url,{"action":"update","stage":"follow_up","assigned_to":"Marcus Reed · Sales","notes":"Prepare two family SUVs for the demo visit."})
        s.refresh_from_db();tools.sync_crm(s)
        lead=DemoCRMLead.objects.get(session=s)
        self.assertEqual(lead.stage,"follow_up")
        self.assertIn("two family SUVs",lead.staff_notes)
        self.assertEqual(Lead.objects.count(),0)
        self.assertTrue(self.client.get(reverse("experience_crm_state"),{"session":s.pk}).json()["has_customer"])

    def finance(self, session, action="open", client=None, **data):
        return (client or self.client).post(reverse("experience_finance"), json.dumps({"session": str(session.pk), "action": action, **data}), content_type="application/json")

    def finance_fields(self, **changes):
        return {"name": "Taylor Demo", "phone": "202-555-0146", "email": "taylor@example.com",
                "financing_preference": "dealer_financing", "stock": "VM-0101", "sample_profile": "employed",
                "down_payment": "5000", "term_months": "60", "demo_acknowledged": True, **changes}

    def test_phone_email_capture_validates_before_mutating_customer(self):
        s = self.start()
        result = tools.execute(s, "update_customer", {"phone": "+1 (202) 555-0146", "email": "taylor@example.com", "financing_preference": "own_financing"})
        self.assertEqual(result['phone'], '+1 (202) 555-0146')
        self.assertEqual(result['email'], 'taylor@example.com')
        tools.sync_crm(s);s.save()
        self.assertEqual(DemoCRMLead.objects.get(session=s).snapshot['customer']['email'], 'taylor@example.com')
        previous = deepcopy(s.state['customer'])
        for fields in ({'phone': 'not-a-number'}, {'email': 'invalid'}, {'phone': '123'}, {'financing_preference': 'approved'}):
            self.assertIn('error', tools.execute(s, 'update_customer', dict(fields, name='Should not be saved')))
            self.assertEqual(s.state['customer'], previous)

    def test_financing_tool_requires_agreement_and_available_vehicle(self):
        s = self.start()
        for fields in ({'stock':'VM-0101','confirmed_by_customer':False}, {'stock':'VM-1902','confirmed_by_customer':True}):
            self.assertIn('error', tools.execute(s, 'open_demo_finance_application', fields))
            self.assertNotIn('financing_application', s.state)
        result = tools.execute(s, 'open_demo_finance_application', {'stock':'VM-0101','confirmed_by_customer':True})
        self.assertEqual(result['application']['status'], 'draft')
        self.assertEqual(result['action'], 'open_finance_application')
        self.assertEqual(result['application']['vehicle']['stock'], 'VM-0101')
        self.assertNotIn('submit_demo_finance_application', tools.TOOL_MODELS)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_ai_intake_opens_form_then_customer_submits_to_crm(self):
        s = self.start()
        with patch('assistant_ai.services.PlatformAIService.tool_completion', side_effect=[
            completion(calls=[('update_customer', {'name':'Taylor Demo','phone':'202-555-0146','email':'taylor@example.com','financing_preference':'dealer_financing'}), ('open_demo_finance_application', {'stock':'VM-0101','confirmed_by_customer':True})]),
            completion("I'm opening the fictional financing application. Review the sample profile and click Submit demo application.")]):
            response = self.turn(s, "Use Taylor Demo, 202-555-0146, taylor@example.com. Yes, open the demo financing form for the Palisade.")
        self.assertEqual(response.status_code, 200)
        application = response.json()['state']['financing_application']
        self.assertEqual(application['status'], 'draft')
        with patch('openai.OpenAI', side_effect=AssertionError('Submitting the demo must not call any AI or lender')):
            response = self.finance(s, 'submit', application_id=application['id'], fields=self.finance_fields())
        self.assertEqual(response.status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.state['financing_application']['status'], 'submitted')
        self.assertEqual(s.state['financing_application']['financial_sample']['employer'], 'Example Design Studio')
        self.assertEqual(s.state['financing_application']['decision'], 'Not evaluated — demonstration only')
        url = reverse('experience_crm') + '?session=' + str(s.pk)
        self.client.post(url, {'action':'signin'})
        page = self.client.get(url)
        for text in ('Taylor Demo','202-555-0146','taylor@example.com','VM-0101',application['id'],'Demo financing application submitted','Alex Morgan · Finance'):
            self.assertContains(page, text)
        self.assertEqual(DemoCRMLead.objects.count(), 1)
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(ConsultationRequest.objects.exists())

    def test_finance_form_rejects_invalid_contacts_non_sample_data_and_missing_ack(self):
        s = self.start()
        application = self.finance(s).json()['state']['financing_application']
        for changes in ({'email':'invalid'}, {'phone':'invalid'}, {'demo_acknowledged':False}, {'sample_profile':'my-real-employer'}, {'down_payment':'12345'}, {'stock':'VM-1902'}, {'term_months':'100'}):
            fields = self.finance_fields();fields.update(changes)
            response = self.finance(s, 'submit', application_id=application['id'], fields=fields)
            self.assertEqual(response.status_code, 400, changes)
            self.assertIn(next(iter(changes)), response.json()['errors'])
        fields = self.finance_fields();fields['ssn'] = 'rejected-placeholder'
        self.assertEqual(self.finance(s, 'submit', application_id=application['id'], fields=fields).status_code, 400)
        s.refresh_from_db()
        self.assertEqual(s.state['financing_application']['status'], 'draft')
        self.assertNotIn('rejected-placeholder', json.dumps(s.state))
        self.assertFalse(DemoEvent.objects.filter(kind='finance_submitted').exists())

    def test_finance_submission_retry_is_idempotent_and_preserves_booking(self):
        s = self.start()
        slot = tools.execute(s,'get_available_sales_slots',{'day':'tomorrow'})['slots'][0]
        tools.execute(s,'create_demo_sales_appointment',{'slot_id':slot['id'],'stock':'VM-0101','confirmed_by_customer':True});s.save()
        application = self.finance(s).json()['state']['financing_application']
        self.assertEqual(application['stock'], 'VM-0101')
        for _ in range(2):
            self.assertEqual(self.finance(s, 'submit', application_id=application['id'], fields=self.finance_fields()).status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.state['appointments']['sales']['vehicle']['stock'], 'VM-0101')
        self.assertEqual(s.state['stage'], 'appointment')
        self.assertEqual(DemoEvent.objects.filter(kind='finance_submitted').count(), 1)
        self.assertEqual(DemoCRMActivity.objects.filter(action='Demo financing application submitted').count(), 1)
        self.assertEqual(self.finance(s).json()['state']['financing_application']['status'], 'submitted')

    def test_finance_isolation_reset_expiry_csrf_and_inflight_guard(self):
        s = self.start();other = Client()
        self.assertEqual(self.finance(s, client=other).status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.finance(s, client=csrf_client).status_code, 403)
        s.busy_until = timezone.now() + timedelta(seconds=30);s.save()
        self.assertEqual(self.finance(s).status_code, 409)
        s.busy_until = None;s.save()
        self.assertEqual(self.finance(s, 'submit', application_id='fake', fields=self.finance_fields()).status_code, 409)
        self.assertEqual(self.finance(s).status_code, 200)
        self.action(s, 'reset')
        self.assertEqual(self.finance(s).status_code, 404)
        self.assertFalse(DemoCRMLead.objects.filter(session=s).exists())
        s.refresh_from_db();self.assertNotIn('financing_application',s.state)
        expired = self.start();expired.expires_at=timezone.now()-timedelta(seconds=1);expired.save()
        self.assertEqual(self.finance(expired).status_code,404)

    def test_finance_business_profile_and_undecided_vehicle(self):
        s = self.start();application=self.finance(s).json()['state']['financing_application']
        fields=self.finance_fields();fields.update(sample_profile='business',stock='',term_months='undecided')
        result=self.finance(s,'submit',application_id=application['id'],fields=fields).json()['state']['financing_application']
        self.assertEqual(result['financial_sample']['applicant_type'],'Business')
        self.assertIsNone(result['vehicle'])

    def test_finance_controls_render_without_live_ai(self):
        response=self.client.get(reverse('experience_home'))
        self.assertContains(response,'id="financeDialog"')
        self.assertContains(response,'name="finance-phone"')
        self.assertContains(response,'name="finance-email"')
        self.assertContains(response,'Submit demo application')
        self.assertNotContains(response,'name="ssn"')
        self.assertNotContains(response,'name="income"')

    def test_finance_form_uses_pinned_inventory_after_manager_edits(self):
        s = self.start()
        content = deepcopy(self.exp.current_revision.content)
        content['inventory'][0]['status'] = 'sold'
        revision = DemoRevision.objects.create(experience=self.exp, version='manager-new-inventory', content=content)
        self.exp.current_revision = revision;self.exp.save()
        response = self.finance(s)
        self.assertIn('VM-0101', [v['stock'] for v in response.json()['finance_options']])
        application = response.json()['state']['financing_application']
        self.assertEqual(self.finance(s,'submit',application_id=application['id'],fields=self.finance_fields()).status_code,200)
        newer = self.start()
        self.assertNotIn('VM-0101', [v['stock'] for v in self.finance(newer).json()['finance_options']])

    def test_seed_upgrades_original_content_but_preserves_manager_revision(self):
        old = DemoRevision.objects.create(experience=self.exp, version='velocity-2026.1.1', content=seed_content())
        self.exp.current_revision=old;self.exp.save()
        call_command('seed_demo_center',stdout=StringIO())
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.current_revision.version,'velocity-2026.1.3')
        custom=DemoRevision.objects.create(experience=self.exp,version='manager-custom',content=seed_content())
        self.exp.current_revision=custom;self.exp.save()
        call_command('seed_demo_center',stdout=StringIO())
        self.exp.refresh_from_db()
        self.assertEqual(self.exp.current_revision,custom)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_ai_booking_flows_to_fictional_staff_workspace(self):
        s = self.start()
        with patch('assistant_ai.services.PlatformAIService.tool_completion', side_effect=[
            completion(calls=[("update_customer", {"name": "Taylor Demo", "interest": "Hyundai Palisade"}), ("get_available_sales_slots", {"day": "tomorrow"})]),
            completion("I have these demo test-drive times tomorrow. Which works for you?")]):
            self.assertEqual(self.turn(s, "I'm Taylor Demo. I'd like to see the Palisade tomorrow.").status_code, 200)
        s.refresh_from_db()
        slot = s.state['slots'][0]
        with patch('assistant_ai.services.PlatformAIService.tool_completion', side_effect=[
            completion(calls=[("create_demo_sales_appointment", {"slot_id": slot['id'], "stock": "VM-0101", "confirmed_by_customer": True})]),
            completion(calls=[("create_demo_bdc_handoff", {"summary": "Taylor requested a Palisade test drive and selected the first offered time tomorrow.", "recommended_follow_up": "Prepare the Palisade for the demo visit.", "temperature": "appointment"})]),
            completion("Your demo visit is confirmed. You can see it in the dealership CRM.")]):
            self.assertEqual(self.turn(s, "Yes, book that first offered time for me.").status_code, 200)
        url = reverse('experience_crm') + '?session=' + str(s.pk)
        self.client.post(url, {'action': 'signin'})
        page = self.client.get(url)
        self.assertContains(page, 'Taylor Demo')
        self.assertContains(page, slot['label'])
        self.assertContains(page, 'Demo appointment booked')
        self.assertContains(page, 'Prepare the Palisade')
        self.assertEqual(DemoCRMLead.objects.count(), 1)
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(ConsultationRequest.objects.exists())

    def test_retention_clears_expired_demo_records_only(self):
        old = self.start()
        current = self.start()
        for s in (old, current):
            tools.execute(s, 'update_customer', {'name': 'Fictional customer', 'interest': 'SUV'})
            tools.sync_crm(s)
            s.transcript = [{'role': 'user', 'content': 'A fictional example'}]
            s.save()
        old.expires_at = timezone.now() - timedelta(days=15)
        old.save()
        call_command('purge_demo_sessions', dry_run=True, stdout=StringIO())
        self.assertEqual(DemoCRMLead.objects.count(), 2)
        call_command('purge_demo_sessions', stdout=StringIO())
        old.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual((old.state, old.transcript), ({}, []))
        self.assertTrue(current.transcript)
        self.assertEqual(list(DemoCRMLead.objects.values_list('session_id', flat=True)), [current.pk])
        self.assertEqual(DemoEvent.objects.filter(kind='started').count(), 2)

    @override_settings(PLATFORM_OPENAI_API_KEY="")
    def test_missing_ai_is_honest_no_canned_reply_or_fake_customer(self):
        s=self.start();r=self.turn(s)
        self.assertEqual(r.status_code,503)
        self.assertEqual(r.json()["code"],"not_configured")
        s.refresh_from_db();self.assertEqual(s.transcript,[])
        self.assertFalse(DemoCRMLead.objects.exists())

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_tool_conversation_grounding_and_idempotent_retry(self):
        s=self.start();request_id=str(uuid.uuid4())
        with patch('assistant_ai.services.PlatformAIService.tool_completion',side_effect=[
            completion(calls=[("search_inventory",{"max_price":50000,"rows":3,"drivetrain":"AWD"}),("update_customer",{"interest":"Three-row SUV","budget":"Under $50,000"})]),
            completion(calls=[("create_demo_bdc_handoff",{"summary":"Looking for an AWD three-row SUV under $50,000.","recommended_follow_up":"Ask about preferred brands and timing.","temperature":"qualified"})]),
            completion("Here are matching three-row SUVs. Is new or pre-owned a better fit?")]) as mocked:
            r=self.turn(s,request_id=request_id)
            self.assertEqual(r.status_code,200,r.content)
            repeat=self.turn(s,request_id=request_id)
            self.assertEqual(repeat.status_code,200)
            self.assertEqual(mocked.call_count,3)
            prompt=mocked.call_args_list[0].kwargs['messages'][0]['content']
            self.assertNotIn('DEMO-VELOCITY-020',prompt)
        s.refresh_from_db();self.assertEqual(s.turns,1)
        self.assertEqual(DemoCRMLead.objects.count(),1)
        self.assertEqual(len(s.transcript),2)
        self.assertEqual(DemoEvent.objects.filter(kind="tool").count(),3)
        self.assertEqual(DemoEvent.objects.get(kind="turn").metadata["mode"],"text")
        self.assertFalse(Lead.objects.exists())

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_ai_failure_and_busy_leave_workflow_uncommitted(self):
        s=self.start()
        with patch('assistant_ai.services.PlatformAIService.tool_completion',side_effect=[completion(calls=[("update_customer",{"name":"Partial","interest":"SUV"})]),RuntimeError("provider failed")]):
            self.assertEqual(self.turn(s).status_code,503)
        s.refresh_from_db();self.assertEqual(s.state["customer"]["name"],"Demo Customer")
        self.assertFalse(DemoCRMLead.objects.exists())
        self.assertEqual(s.transcript,[])
        self.assertIsNone(s.lease)
        s.busy_until=timezone.now()+timedelta(minutes=1);s.save()
        self.assertEqual(self.turn(s).status_code,409)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_reset_during_ai_turn_cannot_restore_customer(self):
        s=self.start()
        def reset_during_turn(session,*args):
            self.action(s,"reset")
            session.state["customer"]["name"]="Late response"
            return "Late answer",[],20
        with patch('core.experience.engine.converse',side_effect=reset_during_turn):
            self.assertEqual(self.turn(s).status_code,409)
        s.refresh_from_db();self.assertEqual(s.state,{})
        self.assertEqual(s.transcript,[])
        self.assertFalse(DemoCRMLead.objects.exists())

    def test_signed_growth_assessment_real_submission_only(self):
        self.client.force_login(self.rep);s=self.start(scenario="fresh-lead")
        token=assessment_token(s)
        self.client.get(reverse("growth_assessment"),{"demo_ref":token})
        self.action(s,"assessment_clicked")
        self.assertFalse(Lead.objects.exists());self.assertFalse(DemoConversion.objects.exists())
        fields={"name":"Business Owner","email":"owner@example.com","phone":"","business_name":"Example Dealership","industry":"Automotive","message":"Please arrange a real Growth Assessment.","demo_ref":token}
        r=self.client.post(reverse("growth_assessment"),fields)
        self.assertEqual(r.status_code,302)
        conversion=DemoConversion.objects.get();lead=Lead.objects.get()
        self.assertEqual(conversion.session,s);self.assertEqual(conversion.scenario,"fresh-lead")
        self.assertEqual(lead.assigned_to,self.rep)
        self.assertEqual(lead.notes,fields["message"])
        self.assertFalse(DemoCRMLead.objects.exists())
        self.assertEqual(DemoEvent.objects.filter(kind="assessment_requested").count(),1)

    def test_forged_assessment_ref_has_no_attribution(self):
        self.client.post(reverse("growth_assessment"),{"name":"Owner","email":"owner@example.com","industry":"Automotive","business_name":"Example","message":"Inquiry","demo_ref":"forged"})
        self.assertFalse(DemoConversion.objects.exists())
        self.assertIsNone(Lead.objects.get().assigned_to)

    def test_owner_management_versions_and_no_history_mutation(self):
        s=self.start();self.client.force_login(self.owner)
        response=self.client.get(reverse("experience_manage"));self.assertEqual(response.status_code,200)
        content=deepcopy(self.exp.current_revision.content);content['business']['name']='Velocity Motors, revised'
        r=self.client.post(reverse("experience_manage"),{"action":"content","content":json.dumps(content)})
        self.assertEqual(r.status_code,302)
        self.exp.refresh_from_db();s.refresh_from_db()
        self.assertNotEqual(self.exp.current_revision_id,s.revision_id)
        self.assertEqual(s.revision.content['business']['name'],'Velocity Motors')
        content['inventory'][0]['image']='https://outside.example/image.png'
        r=self.client.post(reverse("experience_manage"),{"action":"content","content":json.dumps(content)})
        self.assertContains(r,"Images must use local")
        self.assertEqual(DemoRevision.objects.count(),2)

    def test_csrf_is_required_for_conversation_and_crm_signin(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("experience_session"),'{}',content_type='application/json').status_code,403)
        s=self.start()
        self.assertEqual(client.post(reverse("experience_crm")+'?session='+str(s.pk),{"action":"signin"}).status_code,403)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_voice_input_validation_and_text_fallback(self):
        s=self.start();url=reverse("experience_transcribe")+'?session='+str(s.pk)
        self.assertEqual(self.client.post(url,b'bad',content_type='application/octet-stream').status_code,400)
        with patch('openai.OpenAI') as provider:
            provider.return_value.audio.transcriptions.create.side_effect=RuntimeError('failed')
            r=self.client.post(url,b'a'*1000,content_type='audio/mp4')
            self.assertEqual(r.status_code,503)
            self.assertIn('type',r.json()['error'])
        with patch('assistant_ai.services.PlatformAIService.tool_completion',return_value=completion('You can continue by typing.')):
            self.assertEqual(self.turn(s).status_code,200)
        self.assertEqual(DemoEvent.objects.filter(kind='voice_error').count(),1)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_voice_transcript_returns_text_without_saving_audio(self):
        s=self.start()
        with patch('openai.OpenAI') as provider:
            provider.return_value.audio.transcriptions.create.return_value.text='Three rows and AWD, please.'
            r=self.client.post(reverse('experience_transcribe')+'?session='+str(s.pk),b'a'*1000,content_type='audio/mp4')
            self.assertEqual(r.json()['text'],'Three rows and AWD, please.')
        s.refresh_from_db();self.assertEqual(s.transcript,[])
        self.assertEqual(s.turns,0)
        self.assertFalse(DemoCRMLead.objects.exists())

    def test_speech_cannot_be_used_as_arbitrary_text_generator(self):
        s=self.start()
        r=self.client.post(reverse('experience_speech'),json.dumps({'session':str(s.pk),'text':'Attacker supplied arbitrary text','turn':0}),content_type='application/json')
        self.assertEqual(r.status_code,400)

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_session_limits_and_rate_limits(self):
        s=self.start();s.turns=30;s.save()
        with patch('assistant_ai.services.PlatformAIService.tool_completion') as provider:
            self.assertEqual(self.turn(s).status_code,429)
            provider.assert_not_called()
        with patch('core.experience.views.consume_budget',return_value=False):
            self.assertEqual(self.action(s,'share').status_code,429)

    def test_expired_session_cannot_be_used(self):
        s=self.start();s.expires_at=timezone.now()-timedelta(seconds=1);s.save()
        self.assertEqual(self.action(s,'handoff').status_code,404)

    def test_content_validation_seed_and_scenario_identifiers(self):
        self.assertEqual(views.validate_content(seed_content())['business']['name'],'Velocity Motors')
        bad=seed_content();bad['inventory'][1]['stock']=bad['inventory'][0]['stock']
        with self.assertRaises(ValueError):views.validate_content(bad)
        bad=seed_content();bad['scenarios'][0]['slug']='unsupported'
        with self.assertRaises(ValueError):views.validate_content(bad)
