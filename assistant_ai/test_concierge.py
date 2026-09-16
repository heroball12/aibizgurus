import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.catalog import PRICING_PLANS
from core.models import ConsultationRequest
from crm.models import Lead
from . import concierge
from .models import ConciergeCall, ConciergeSubmission


@override_settings(VIDEO_CONCIERGE_ENABLED=True, RUNWAYML_API_SECRET='test-server-secret', RUNWAY_AVATAR_ID='test-character', VIDEO_CONCIERGE_DAILY_LIMIT=20, VIDEO_CONCIERGE_HOURLY_LIMIT=3)
class ConciergeTests(TestCase):
    def post(self, name, data=None, args=None, client=None):
        return (client or self.client).post(reverse(name,args=args), data=json.dumps(data or {}),content_type='application/json')

    def start(self):
        with patch('assistant_ai.concierge.create_session',return_value={'id':str(uuid.uuid4())}):
            response=self.post('concierge_start',{'consent':True,'page':'pricing'})
        self.assertEqual(response.status_code,201)
        return response.json()

    def test_page_has_real_media_controls_and_no_permanent_secret(self):
        response=self.client.get(reverse('concierge'))
        self.assertContains(response,'guideTextForm')
        self.assertContains(response,'Speak')
        self.assertContains(response,'guideMinimize')
        self.assertNotContains(response,'test-server-secret')
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_start_requires_explicit_call_consent(self):
        with patch('assistant_ai.concierge.create_session') as api:
            self.assertEqual(self.post('concierge_start',{'consent':'true'}).status_code,400)
            self.assertEqual(self.post('concierge_start',{}).status_code,400)
            api.assert_not_called()

    def test_terms_can_be_read_without_accepting_or_starting_a_call(self):
        with patch('assistant_ai.concierge.create_session') as api:
            page=self.client.get(reverse('concierge'))
            terms=self.client.get(reverse('concierge_terms'))
            self.assertContains(page,'data-guide-terms')
            self.assertContains(page,'id="guideTermsDialog"')
            self.assertContains(terms,'AI Business Gurus Terms of Service')
            self.assertContains(terms,'Audio, conversation recordings and transcripts may be retained by Runway')
            self.assertFalse(ConciergeCall.objects.exists())
            api.assert_not_called()

    def test_post_only_and_csrf_required(self):
        self.assertEqual(self.client.get(reverse('concierge_start')).status_code,405)
        strict=Client(enforce_csrf_checks=True)
        self.assertEqual(self.post('concierge_start',{'consent':True},client=strict).status_code,403)

    @override_settings(VIDEO_CONCIERGE_ENABLED=False)
    def test_unconfigured_does_not_call_provider(self):
        with patch('assistant_ai.concierge.create_session') as api:
            self.assertEqual(self.post('concierge_start',{'consent':True}).status_code,503)
            api.assert_not_called()

    def test_call_is_bound_to_originating_session(self):
        call=self.start(); other=Client()
        for name in ['concierge_poll','concierge_stop']:
            self.assertEqual(self.post(name,args=[call['id']],client=other).status_code,404)

    def test_one_active_call_per_browser(self):
        self.start()
        with patch('assistant_ai.concierge.create_session') as api:
            self.assertEqual(self.post('concierge_start',{'consent':True}).status_code,409)
            api.assert_not_called()

    def test_credentials_issued_once_and_never_cached_or_persisted(self):
        call=self.start()
        with patch('assistant_ai.concierge.runway_request',return_value={'status':'READY','sessionKey':'ephemeral-token'}):
            response=self.post('concierge_poll',args=[call['id']])
            self.assertEqual(response.json()['credentials']['sessionKey'],'ephemeral-token')
            self.assertIn('no-store',response.headers['Cache-Control'])
            self.assertEqual(self.post('concierge_poll',args=[call['id']]).status_code,409)
        self.assertNotIn('ephemeral-token',str(ConciergeCall.objects.values().first()))

    def test_provider_failure_releases_call_and_does_not_leak_error(self):
        with patch('assistant_ai.concierge.create_session',side_effect=concierge.RunwayError('secret provider detail')):
            response=self.post('concierge_start',{'consent':True})
        self.assertEqual(response.status_code,502)
        self.assertNotContains(response,'secret provider detail',status_code=502)
        self.assertFalse(ConciergeCall.objects.get().active)

    def test_pending_poll_and_terminal_provider_status(self):
        call=self.start()
        with patch('assistant_ai.concierge.runway_request',return_value={'status':'NOT_READY'}):
            self.assertEqual(self.post('concierge_poll',args=[call['id']]).json()['status'],'pending')
        with patch('assistant_ai.concierge.runway_request',return_value={'status':'FAILED','failure':'private details'}):
            response=self.post('concierge_poll',args=[call['id']])
        self.assertEqual(response.status_code,502)
        self.assertFalse(ConciergeCall.objects.get().active)

    def test_stop_cancels_provider_once(self):
        call=self.start()
        with patch('assistant_ai.concierge.runway_request',return_value={}) as api:
            self.assertEqual(self.post('concierge_stop',args=[call['id']]).status_code,200)
            self.assertEqual(self.post('concierge_stop',args=[call['id']]).status_code,200)
            api.assert_called_once()
        self.assertFalse(ConciergeCall.objects.get().active)

    def test_cancel_failure_can_be_retried_without_issuing_credentials(self):
        call=self.start()
        with patch('assistant_ai.concierge.runway_request',side_effect=concierge.RunwayError('unavailable')):
            self.assertEqual(self.post('concierge_stop',args=[call['id']]).status_code,502)
        self.assertEqual(self.post('concierge_poll',args=[call['id']]).status_code,409)
        with patch('assistant_ai.concierge.runway_request',return_value={}):
            self.assertEqual(self.post('concierge_stop',args=[call['id']]).status_code,200)

    @override_settings(VIDEO_CONCIERGE_DAILY_LIMIT=0)
    def test_global_cost_cap(self):
        with patch('assistant_ai.concierge.create_session') as api:
            self.assertEqual(self.post('concierge_start',{'consent':True}).status_code,429)
            api.assert_not_called()

    @override_settings(VIDEO_CONCIERGE_HOURLY_LIMIT=0)
    def test_per_visitor_cost_cap(self):
        with patch('assistant_ai.concierge.create_session') as api:
            self.assertEqual(self.post('concierge_start',{'consent':True}).status_code,429)
            api.assert_not_called()

    def test_only_public_guided_pages_can_be_framed(self):
        response=self.client.get(reverse('pricing')+'?guided=1')
        self.assertEqual(response.headers['X-Frame-Options'],'SAMEORIGIN')
        self.assertEqual(response.headers['Content-Security-Policy'],"frame-ancestors 'self'")
        self.assertEqual(self.client.get(reverse('pricing')).headers['X-Frame-Options'],'DENY')
        self.assertEqual(self.client.get(reverse('login')+'?guided=1').headers['X-Frame-Options'],'DENY')
        self.assertEqual(self.client.get(reverse('concierge')+'?guided=1').headers['X-Frame-Options'],'DENY')

    def test_navigation_is_allowlisted_and_initial_page_cannot_escape(self):
        response=self.client.get(reverse('concierge'),{'page':'https://evil.example'})
        self.assertEqual(response.context['config']['initialPage'],'home')
        self.assertNotContains(response,'evil.example')
        for page in concierge.pages().values():
            self.assertTrue(page['path'].startswith('/'))
            self.assertFalse(page['path'].startswith('//'))
        self.assertLessEqual(len(concierge.pages()),20)

    def test_personality_uses_same_prices_as_site_and_fits_provider(self):
        prompt=concierge.personality()
        self.assertLessEqual(len(prompt),10000)
        for plan in PRICING_PLANS:
            self.assertIn(plan['setup'],prompt)
            self.assertIn(plan['monthly'],prompt)

    def followup_data(self):
        return {'name':'Test Customer','email':'customer@example.com','business_name':'Example Company','industry':'Home services','message':'I want to improve follow-up.','consent':'on','submission_id':str(uuid.uuid4())}

    def test_followup_creates_real_crm_handoff_once(self):
        data=self.followup_data()
        first=self.client.post(reverse('concierge_followup'),data)
        second=self.client.post(reverse('concierge_followup'),data)
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.json(),second.json())
        self.assertEqual(ConsultationRequest.objects.count(),1)
        self.assertEqual(ConciergeSubmission.objects.count(),1)
        self.assertEqual(Lead.objects.filter(source='Video concierge follow-up',lead_type='internal_sales').count(),1)

    def test_followup_requires_valid_email_and_customer_consent(self):
        data=self.followup_data();data['consent']='';data['email']='invalid'
        response=self.client.post(reverse('concierge_followup'),data)
        self.assertEqual(response.status_code,400)
        self.assertFalse(ConsultationRequest.objects.exists())
        self.assertFalse(Lead.objects.exists())

    def test_followup_honeypot_and_length_limit(self):
        data=self.followup_data();data['website']='bot'
        self.assertEqual(self.client.post(reverse('concierge_followup'),data).status_code,400)
        data.pop('website');data['message']='x'*4001
        self.assertEqual(self.client.post(reverse('concierge_followup'),data).status_code,400)

    def test_followup_receipt_cannot_be_reused_by_other_browser(self):
        data=self.followup_data()
        self.client.post(reverse('concierge_followup'),data)
        response=Client().post(reverse('concierge_followup'),data)
        self.assertEqual(response.status_code,409)
        self.assertEqual(ConsultationRequest.objects.count(),1)

    def connected_call(self):
        call=self.start()
        ConciergeCall.objects.filter(pk=call['id']).update(status='issued')
        return call

    def test_typed_input_requires_owned_live_call_and_is_bounded(self):
        call=self.start()
        self.assertEqual(self.post('concierge_text',{'message':'hello'},args=[call['id']]).status_code,409)
        ConciergeCall.objects.filter(pk=call['id']).update(status='issued')
        self.assertEqual(self.post('concierge_text',{'message':'hello'},args=[call['id']],client=Client()).status_code,404)
        for text in ['', 'x'*501, ['malformed']]:
            self.assertEqual(self.post('concierge_text',{'message':text},args=[call['id']]).status_code,400)

    def test_typed_message_uses_server_voice_and_private_task_receipt(self):
        call=self.connected_call();task_id=str(uuid.uuid4())
        with patch('assistant_ai.concierge.runway_request',return_value={'id':task_id}) as api:
            response=self.post('concierge_text',{'message':'Show pricing','voice':'attacker'},args=[call['id']])
        self.assertEqual(response.status_code,201)
        self.assertEqual(api.call_args.args[2]['voice']['presetId'],'Maya')
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertNotContains(response,'test-server-secret',status_code=201)
        token=response.json()['token']
        with patch('assistant_ai.concierge.runway_request',return_value={'status':'SUCCEEDED','output':['https://example.cloudfront.net/speech.mp3']}),patch('assistant_ai.concierge.fetch_speech_audio',return_value=b'fake-mp3'):
            audio=self.post('concierge_text_status',{'token':token},args=[call['id']])
        self.assertEqual(audio.status_code,200)
        self.assertEqual(audio['Content-Type'],'audio/mpeg')
        self.assertEqual(audio.content,b'fake-mp3')

    def test_forged_tts_receipt_cannot_poll_arbitrary_tasks(self):
        call=self.connected_call()
        with patch('assistant_ai.concierge.runway_request') as api:
            self.assertEqual(self.post('concierge_text_status',{'token':'forged'},args=[call['id']]).status_code,400)
            api.assert_not_called()

    def test_speech_proxy_rejects_non_provider_urls(self):
        for url in ['http://localhost/audio','https://127.0.0.1/audio','file:///etc/passwd','https://cloudfront.net.attacker.example/secret']:
            with self.assertRaises(concierge.RunwayError):concierge.fetch_speech_audio(url)
