from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from crm.models import Lead, LeadActivity, LeadNote
from .models import ActivityLog, EmployeeLeadEvent
from .history import batch
from .threadlocal import clear_current_request

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class HistoryRecoveryTests(TestCase):
    def setUp(self):
        clear_current_request()
        self.rep = get_user_model().objects.create_user(username='historical-rep', role='employee')
        self.owner = get_user_model().objects.create_user(username='historical-owner', role='owner')
        self.lead = Lead.objects.create(business_name='Historical business', assigned_to=self.owner)
        self.at = timezone.now()-timedelta(days=40)
        self.cutoff = self.at+timedelta(days=1)
    def old(self, obj, offset=0):
        obj.__class__.objects.filter(pk=obj.pk).update(created_at=self.at+timedelta(seconds=offset))
        return obj
    def log(self, **kwargs):
        offset=kwargs.pop('offset',0)
        return self.old(ActivityLog.objects.create(actor=self.rep, actor_username=self.rep.username, method='POST', path=reverse('lead_detail',args=[self.lead.pk]), **kwargs),offset)
    def recover(self, apply=True):
        return [batch(source,apply=apply,before=self.cutoff) for source in ('audit','activity','note')]
    def test_multiple_audit_messages_and_note_activity_count_once_original_actor_date(self):
        note=self.old(LeadNote.objects.create(lead=self.lead,user=self.rep,note='Original note'))
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='manual_note',classification_source='manual',raw_note='Original note'))
        for _ in range(2):
            self.log(action='update',model_label='crm.Lead',object_id=str(self.lead.pk))
        self.log(action='create',model_label='crm.LeadNote',object_id=str(note.pk))
        self.log(action='request',status_code=302,offset=1)
        self.recover(False)
        self.assertEqual(EmployeeLeadEvent.objects.count(),0)
        self.recover();self.recover()
        event=EmployeeLeadEvent.objects.get()
        self.assertEqual(event.actor,self.rep)
        self.assertEqual(event.created_at,self.at)
        self.assertTrue(event.historical)
        self.assertTrue(event.counts_as_call)
        self.assertFalse(event.assessment_booked)
    def test_imports_unattributed_and_reads_do_not_become_calls(self):
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='imported_note'))
        self.old(LeadActivity.objects.create(lead=self.lead,activity_type='call'))
        self.log(action='request',status_code=200)
        self.recover()
        self.assertEqual(EmployeeLeadEvent.objects.count(),0)
    def test_documented_call_survives_without_generic_audit_and_recovers_outcome(self):
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='call',inferred_status='appointment_scheduled',metadata={'previous_status':'warm_lead','appointment_at':self.at.isoformat()}))
        self.recover();self.recover()
        event=EmployeeLeadEvent.objects.get()
        self.assertTrue(event.assessment_booked)
        self.assertTrue(event.counts_as_call)
    def test_existing_counter_events_and_post_cutoff_events_not_repeated(self):
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='call'))
        self.old(EmployeeLeadEvent.objects.create(lead=self.lead,lead_key=self.lead.pk,actor=self.rep,actor_name='rep',kind='updated',counts_as_call=True))
        LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='call')
        self.recover()
        self.assertEqual(EmployeeLeadEvent.objects.count(),1)
    def test_owner_only_recovery_and_employee_scorecard_scope(self):
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse('historical_activity')).status_code,302)
        self.assertEqual(self.client.post(reverse('historical_activity')).status_code,302)
        response=self.client.get(reverse('sales_scorecards'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['employee_rows']),1)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('historical_activity')), 'Bring earlier work forward')

    def test_duplicate_note_and_activity_without_request_are_one_record(self):
        self.old(LeadNote.objects.create(lead=self.lead,user=self.rep,note='Shared note'))
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='manual_note',classification_source='manual',raw_note='Shared note'))
        self.recover()
        self.assertEqual(EmployeeLeadEvent.objects.count(),1)

    def test_status_label_alone_does_not_invent_a_confirmed_booking(self):
        self.old(LeadActivity.objects.create(lead=self.lead,user=self.rep,activity_type='call',inferred_status='appointment_scheduled',metadata={'previous_status':'new'}))
        self.recover()
        self.assertFalse(EmployeeLeadEvent.objects.get().assessment_booked)
