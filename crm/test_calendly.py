import copy
import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from audit.models import EmployeeLeadEvent
from .models import Lead, AssessmentBooking, CalendlyConnection
from .calendly import booking_url, connect, CalendarError

@override_settings(CALENDLY_WEBHOOK_SIGNING_KEY='test-signing-secret-with-at-least-32-characters',EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CalendlyTests(TestCase):
    def setUp(self):
        self.rep=get_user_model().objects.create_user(username='calendar-rep',role='employee')
        self.owner=get_user_model().objects.create_user(username='calendar-owner',role='owner')
        self.lead=Lead.objects.create(business_name='Booking business',assigned_to=self.rep,email='prospect@example.com')
        CalendlyConnection.objects.create(pk=1,event_type_uri='https://api.calendly.com/event_types/growth')
        self.now=timezone.now()
        self.uri='https://api.calendly.com/scheduled_events/demo/invitees/one'
    def data(self):
        return {'event':'invitee.created','created_at':self.now.isoformat(),'payload':{'uri':self.uri,'event':'https://api.calendly.com/scheduled_events/demo','updated_at':self.now.isoformat(),'email':self.lead.email,'name':'Sample prospect','tracking':{'utm_content':parse_qs(urlsplit(booking_url(self.lead,self.rep)).query)['utm_content'][0]},'scheduled_event':{'event_type':'https://api.calendly.com/event_types/growth','start_time':(self.now+timedelta(days=1)).isoformat(),'location':{'join_url':'https://example.com/meeting'}}}}
    def send(self,data=None,stamp=None,signature=None):
        body=json.dumps(data or self.data()).encode()
        stamp=str(stamp or int(time.time()))
        digest=signature or hmac.new(b'test-signing-secret-with-at-least-32-characters',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        return self.client.post(reverse('calendly_webhook'),body,content_type='application/json',HTTP_CALENDLY_WEBHOOK_SIGNATURE=f't={stamp},v1={digest}')
    def test_booking_signature_attribution_idempotency_and_no_call(self):
        self.assertEqual(self.send().status_code,200)
        self.assertEqual(self.send().json()['status'],'duplicate')
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'appointment_scheduled')
        event=EmployeeLeadEvent.objects.get();self.assertEqual(event.actor,self.rep)
        self.assertTrue(event.assessment_booked);self.assertFalse(event.counts_as_call)
        self.assertEqual(event.created_at,self.now)
    def test_bad_signature_old_timestamp_and_unconfigured_never_change_data(self):
        self.assertEqual(self.send(signature='bad').status_code,401)
        self.assertEqual(self.send(stamp=int(time.time())-900).status_code,401)
        with override_settings(CALENDLY_WEBHOOK_SIGNING_KEY=''):
            self.assertEqual(self.send().status_code,503)
        self.assertEqual(AssessmentBooking.objects.count(),0)
    def test_cancel_then_late_create_does_not_reopen(self):
        original=self.data();self.send(original)
        canceled=copy.deepcopy(original);canceled['event']='invitee.canceled';canceled['payload']['updated_at']=(self.now+timedelta(seconds=1)).isoformat()
        self.send(canceled);self.send(original)
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'follow_up');self.assertIsNone(self.lead.appointment_at)
        self.assertEqual(EmployeeLeadEvent.objects.filter(assessment_booked=True).count(),1)
    def test_reschedule_new_before_old_cancellation_preserves_new_time(self):
        original=self.data();self.send(original)
        new=copy.deepcopy(original);new['payload'].update(uri=self.uri+'-new',old_invitee=self.uri,updated_at=(self.now+timedelta(seconds=2)).isoformat())
        new['payload']['scheduled_event']['start_time']=(self.now+timedelta(days=2)).isoformat()
        self.send(new)
        original['event']='invitee.canceled';original['payload']['updated_at']=(self.now+timedelta(seconds=1)).isoformat()
        self.send(original)
        self.lead.refresh_from_db();self.assertEqual(self.lead.appointment_at,self.now+timedelta(days=2));self.assertEqual(self.lead.status,'appointment_scheduled')
    def test_duplicate_email_invalid_tracking_dnc_and_manual_conflict_need_review(self):
        data=self.data();data['payload']['tracking']={}
        Lead.objects.create(business_name='Same email',email=self.lead.email)
        self.send(data)
        self.assertIn('unique',AssessmentBooking.objects.get().review_reason)
        self.assertFalse(EmployeeLeadEvent.objects.exists())
        data['payload']['uri']=self.uri+'-invalid';data['payload']['tracking']={'utm_content':'forged'}
        self.send(data);self.assertEqual(AssessmentBooking.objects.exclude(review_reason='').count(),2)
        self.lead.status='do_not_contact';self.lead.save()
        data=self.data();data['payload']['uri']=self.uri+'-dnc';self.send(data)
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'do_not_contact')
    def test_other_event_types_and_invalid_payload_ignored(self):
        data=self.data();data['payload']['scheduled_event']['event_type']='other'
        self.assertEqual(self.send(data).json()['status'],'ignored')
        self.assertEqual(self.send({'event':'invitee.created'}).status_code,400)
        self.assertFalse(AssessmentBooking.objects.exists())
    def test_owner_review_match_and_staff_access_denied(self):
        data=self.data();data['payload']['email']='different@example.com';self.send(data)
        booking=AssessmentBooking.objects.get();self.assertIsNone(booking.lead)
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse('calendly_manage')).status_code,302)
        self.client.force_login(self.owner)
        response=self.client.post(reverse('calendly_manage'),{'action':'match','booking':booking.pk,'lead':self.lead.pk})
        self.assertEqual(response.status_code,302)
        self.lead.refresh_from_db();self.assertEqual(self.lead.status,'appointment_scheduled')
    @override_settings(PUBLIC_BASE_URL='https://aibiz.guru',CALENDLY_API_TOKEN='test-token')
    @patch('crm.calendly.api')
    def test_connection_creates_scoped_signed_subscription(self,api):
        api.side_effect=[{'resource':{'uri':'user','current_organization':'org'}},{'collection':[{'uri':'event-type','scheduling_url':'https://calendly.com/james-aibiz/30min'}]},{'collection':[]},{'resource':{'uri':'subscription'}}]
        connection=connect()
        self.assertEqual(connection.subscription_uri,'subscription')
        payload=api.call_args.kwargs['json']
        self.assertEqual(payload['scope'],'user');self.assertEqual(payload['url'],'https://aibiz.guru/crm/assessments/calendly/webhook/')
        self.assertTrue(payload['signing_key'])
