from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from audit.models import EmployeeLeadEvent
from audit.forms import StaffUserForm
from .models import Lead, SalesFollowUpPlan, SalesWorkSubmission
from .sheet_schema import columns
from .forms import AssessmentForm
from .followups import advance
from assistant_ai.sales_concierge import personality

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class GuidedSellingTests(TestCase):
    def setUp(self):
        self.rep=get_user_model().objects.create_user(username='guided-rep',role='employee')
        self.other=get_user_model().objects.create_user(username='guided-other',role='employee')
        self.owner=get_user_model().objects.create_user(username='guided-owner',role='owner')
        self.lead=Lead.objects.create(business_name='Due business',assigned_to=self.rep,follow_up_date=timezone.localdate()-timedelta(days=1))
        self.new=Lead.objects.create(business_name='New business',assigned_to=self.rep)
        self.client.force_login(self.rep)
    def ticket(self):
        return self.client.get(reverse('guided_sell')).context['outcome_form'].initial['ticket']
    def test_queue_scope_order_and_closed_future_exclusions(self):
        Lead.objects.create(business_name='Future',assigned_to=self.rep,follow_up_date=timezone.localdate()+timedelta(days=2))
        Lead.objects.create(business_name='Blocked',assigned_to=self.rep,status='do_not_contact')
        Lead.objects.create(business_name='Other',assigned_to=self.other)
        response=self.client.get(reverse('guided_sell'))
        self.assertEqual(response.context['lead'],self.lead)
        self.assertEqual(response.context['remaining'],2)
    def test_save_next_plan_and_retry_count_once(self):
        data={'ticket':self.ticket(),'outcome':'no_answer','plan':'introduction','note':'No answer today'}
        for _ in range(2):
            self.assertEqual(self.client.post(reverse('guided_sell'),data).status_code,302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.follow_up_date,timezone.localdate()+timedelta(days=2))
        self.assertEqual(SalesWorkSubmission.objects.count(),1)
        self.assertEqual(EmployeeLeadEvent.objects.filter(counts_as_call=True).count(),1)
        self.assertEqual(self.client.get(reverse('guided_sell')).context['lead'],self.new)
        self.assertTrue(self.lead.follow_up_plan.active)
    def test_skip_is_not_activity(self):
        self.client.post(reverse('guided_sell'),{'ticket':self.ticket(),'action':'skip'})
        self.assertEqual(EmployeeLeadEvent.objects.count(),0)
        self.assertEqual(self.client.get(reverse('guided_sell')).context['lead'],self.new)
    def test_conflicting_change_does_not_overwrite_and_dnc_stops_plan(self):
        ticket=self.ticket()
        SalesFollowUpPlan.objects.create(lead=self.lead,plan='introduction',created_by=self.rep)
        self.lead.status='do_not_contact';self.lead.save()
        result=self.client.post(reverse('guided_sell'),{'ticket':ticket,'outcome':'warm_lead'})
        self.assertEqual(result.status_code,409)
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'do_not_contact')
        self.assertFalse(self.lead.follow_up_plan.active)
    def test_wrong_actor_ticket_and_reassigned_lead(self):
        ticket=self.ticket()
        self.client.force_login(self.other)
        self.client.post(reverse('guided_sell'),{'ticket':ticket,'outcome':'warm_lead'})
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'new')
        self.client.force_login(self.rep)
        self.lead.assigned_to=self.other;self.lead.save()
        self.assertEqual(self.client.post(reverse('guided_sell'),{'ticket':ticket,'outcome':'warm_lead'}).status_code,404)
    def test_plan_steps_date_override_completion_and_booking_stops(self):
        requested=timezone.localdate()+timedelta(days=9)
        self.assertEqual(advance(self.lead,self.rep,'demo',requested),requested)
        advance(self.lead,self.rep,'')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.follow_up_plan.step,1)
        advance(self.lead,self.rep,'');advance(self.lead,self.rep,'')
        self.lead.refresh_from_db();self.assertFalse(self.lead.follow_up_plan.active)
        advance(self.lead,self.rep,'demo')
        self.lead.status='appointment_scheduled';self.lead.save()
        self.lead.refresh_from_db();self.assertFalse(self.lead.follow_up_plan.active)
    def test_callback_requires_date(self):
        response=self.client.post(reverse('guided_sell'),{'ticket':self.ticket(),'outcome':'callback_requested'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(SalesWorkSubmission.objects.exists())

class SpecialistPermissionsTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.rep=User.objects.create_user(username='price-rep',role='employee')
        self.owner=User.objects.create_user(username='price-owner',role='owner')
        self.lead=Lead.objects.create(assigned_to=self.rep,business_name='Pricing business',assessment_brief={'strategy':'Specialist strategy','pricing':'Secret custom scope'})
        self.client.force_login(self.rep)
    def test_rep_cannot_read_or_overwrite_pricing_through_forms_sheets_or_guru(self):
        self.assertNotContains(self.client.get(reverse('lead_detail',args=[self.lead.pk])),'Secret custom scope')
        self.assertNotIn('pricing',AssessmentForm(user=self.rep).fields)
        self.assertNotIn('pricing',[c['key'] for c in columns(self.rep)])
        response=self.client.post(reverse('lead_progress',args=[self.lead.pk]),{'action':'assessment','assessment-goal':'Less admin','assessment-pricing':'Forged'})
        self.assertEqual(response.status_code,302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assessment_brief['pricing'],'Secret custom scope')
        self.assertNotIn('Secret custom scope',personality(self.lead))
    def test_explicit_specialist_and_owner_can_manage_pricing(self):
        self.assertIn('pricing',AssessmentForm(user=self.owner).fields)
        self.rep.is_ai_specialist=True;self.rep.save()
        self.assertIn('pricing',AssessmentForm(user=self.rep).fields)
        self.assertIn('pricing',[c['key'] for c in columns(self.rep)])
    def test_only_owner_can_grant_specialist(self):
        self.assertNotIn('is_ai_specialist',StaffUserForm(actor=self.rep).fields)
        self.assertIn('is_ai_specialist',StaffUserForm(actor=self.owner).fields)
