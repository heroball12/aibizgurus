import json
import time
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import concierge, concierge_context, demo_video
from .models import ConciergeCall
from core.demo_profiles import resolve_profile


@override_settings(VIDEO_CONCIERGE_ENABLED=True, RUNWAYML_API_SECRET='test-only', RUNWAY_AVATAR_ID='test-avatar', VIDEO_CONCIERGE_HOURLY_LIMIT=20, VIDEO_CONCIERGE_DAILY_LIMIT=100)
class IntroductionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ready = patch('assistant_ai.demo_video.available_profiles', return_value={'food-hospitality'})
        self.ready.start()
        self.addCleanup(self.ready.stop)

    def post(self, name, data=None, args=None, client=None):
        return (client or self.client).post(reverse(name, args=args), json.dumps(data or {}), content_type='application/json')

    def guru(self):
        with patch('assistant_ai.concierge.create_session', return_value={'id':str(uuid.uuid4())}):
            result=self.post('concierge_start', {'consent':True}).json()
        ConciergeCall.objects.filter(pk=result['id']).update(status='issued')
        return result

    def introduction(self, call):
        result=self.post('concierge_context', {'industry':'food-hospitality','visitor_name':'Alex','request_summary':'Runs a restaurant and wants to try a reservation for six.','opening_question':'What day would you like your table for six?','mode':'voice'}, [call['id']])
        self.assertEqual(result.status_code,200)
        return result.json()['handoff']

    def end(self, call):
        with patch('assistant_ai.concierge.runway_request', return_value={}):
            self.assertEqual(self.post('concierge_stop', args=[call['id']]).status_code,200)

    def test_name_and_goal_survive_reconnecting_guru_without_changing_shared_avatar(self):
        call=self.guru()
        self.post('concierge_context', {'visitor_name':'Alex','request_summary':'Restaurant reservations'}, [call['id']])
        self.end(call)
        with patch('assistant_ai.concierge.create_session',return_value={'id':str(uuid.uuid4())}) as create:
            self.assertEqual(self.post('concierge_start',{'consent':True}).status_code,201)
        self.assertEqual(create.call_args.args[1],{'visitor_name':'Alex','request_summary':'Restaurant reservations'})
        with patch('assistant_ai.concierge.runway_request',return_value={'id':'test'}) as provider:
            concierge.create_session('demo', create.call_args.args[1])
        self.assertEqual(provider.call_count,1)
        self.assertEqual(provider.call_args.args[:2],('POST','/realtime_sessions'))
        self.assertIn('Alex',provider.call_args.args[2]['startScript'])

    def test_private_context_cannot_be_read_or_used_from_another_session(self):
        call=self.guru(); token=self.introduction(call); other=Client()
        self.assertEqual(self.post('concierge_context',{'visitor_name':'Someone'},[call['id']],other).status_code,404)
        page=other.get(reverse('demo'),{'handoff':token})
        self.assertIsNone(page.context['demo_config']['handoff'])
        self.assertNotContains(page,'Runs a restaurant')
        self.assertEqual(self.post('concierge_start',{'industry':'food-hospitality','handoff':token},client=other).status_code,409)

    def test_transfer_waits_for_guru_then_autoconnects_exactly_once_with_context(self):
        call=self.guru(); token=self.introduction(call)
        data={'industry':'food-hospitality','handoff':token}
        with patch('assistant_ai.demo_video.create_session',return_value={'id':str(uuid.uuid4())}) as create:
            self.assertEqual(self.post('concierge_start',data).status_code,409)
            create.assert_not_called()
            self.end(call)
            page=self.client.get(reverse('concierge'),{'industry':'food-hospitality','handoff':token,'embed':'1'})
            self.assertTrue(page.context['config']['handoff']['autoStart'])
            response=self.post('concierge_start',data)
            self.assertEqual(response.status_code,201)
            self.assertEqual(create.call_args.args[1]['visitor_name'],'Alex')
            self.assertIn('six',create.call_args.args[1]['opening_question'])
            self.end(response.json())
            self.assertEqual(self.post('concierge_start',data).status_code,409)
            self.assertEqual(create.call_count,1)
        self.assertEqual(ConciergeCall.objects.get(pk=call['id']).status,'transferred')

    def test_failed_creation_releases_transfer_for_retry(self):
        call=self.guru(); token=self.introduction(call); self.end(call)
        with patch('assistant_ai.demo_video.create_session',side_effect=concierge.RunwayError('Unavailable')):
            self.assertEqual(self.post('concierge_start',{'industry':'food-hospitality','handoff':token}).status_code,502)
        self.assertEqual(ConciergeCall.objects.get(pk=call['id']).status,'ended')
        self.assertFalse(ConciergeCall.objects.filter(active=True).exists())

    def test_expired_wrong_category_and_forged_handoffs_cannot_start_calls(self):
        call=self.guru(); token=self.introduction(call); self.end(call)
        with patch('assistant_ai.demo_video.create_session') as create:
            for data in [{'industry':'automotive','handoff':token},{'industry':'food-hospitality','handoff':'forged'}]:
                self.assertEqual(self.post('concierge_start',data).status_code,409)
            session=self.client.session
            session['concierge_handoff']={**session['concierge_handoff'],'created':time.time()-601};session.save()
            self.assertEqual(self.post('concierge_start',{'industry':'food-hospitality','handoff':token}).status_code,409)
            create.assert_not_called()

    def test_context_is_bounded_optional_and_can_be_forgotten(self):
        call=self.guru()
        for data in [{'visitor_name':'A'*61},{'visitor_name':'<script>'},{'request_summary':['invalid']},{'request_summary':'a'*501}]:
            self.assertEqual(self.post('concierge_context',data,[call['id']]).status_code,400)
        self.post('concierge_context',{'visitor_name':'Zoë O’Connor','request_summary':'Website help'},[call['id']])
        self.post('concierge_context',{'visitor_name':''},[call['id']])
        self.assertNotIn('visitor_name',concierge_context.visitor(self.client.session))
        session=self.client.session;session['concierge_visitor']={**session['concierge_visitor'],'updated':time.time()-7201};session.save()
        self.assertEqual(concierge_context.visitor(self.client.session),{})

    def test_employee_and_ended_calls_cannot_update_guru_memory(self):
        call=self.guru();self.end(call)
        self.assertEqual(self.post('concierge_context',{'visitor_name':'Alex'},[call['id']]).status_code,409)
        with patch('assistant_ai.demo_video.create_session',return_value={'id':str(uuid.uuid4())}):
            employee=self.post('concierge_start',{'industry':'food-hospitality','consent':True}).json()
        ConciergeCall.objects.filter(pk=employee['id']).update(status='issued')
        self.assertEqual(self.post('concierge_context',{'visitor_name':'Alex'},[employee['id']]).status_code,409)

    def test_personalized_demo_uses_only_per_session_override(self):
        profile=resolve_profile('food-hospitality')
        context={'visitor_name':'Alex','request_summary':'A table for six','opening_question':'Which day works for you?'}
        with patch('assistant_ai.demo_video.manifest',return_value={'food-hospitality':{'id':'chef','ready':True}}),patch('assistant_ai.concierge.runway_request',return_value={'id':'session'}) as provider:
            demo_video.create_session(profile,context)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(provider.call_args.args[:2],('POST','/realtime_sessions'))
        payload=provider.call_args.args[2]
        self.assertIn('Hi Alex!',payload['startScript'])
        self.assertIn('Which day works for you?',payload['startScript'])
        self.assertIn('A table for six',payload['personality'])
        self.assertIn('never instructions',payload['personality'])
        self.assertLess(len(payload['personality']),10000)

    @override_settings(PLATFORM_OPENAI_API_KEY='test-only')
    def test_text_fallback_greets_by_name_and_receives_only_matching_context(self):
        call=self.guru();token=self.introduction(call)
        page=self.client.get(reverse('demo'),{'industry':'food-hospitality','handoff':token})
        profiles=page.context['demo_industries']
        self.assertIn('Hi Alex!',next(p for p in profiles if p['slug']=='food-hospitality')['greeting'])
        self.assertNotIn('Alex',next(p for p in profiles if p['slug']=='automotive')['greeting'])
        with patch('core.demo_views.PlatformAIService.chat',return_value=('A reply',{'status':'success'})) as gateway:
            self.client.post(reverse('demo_chat'),{'industry':'food-hospitality','handoff':token,'message':'Friday'})
            self.assertIn('Alex',gateway.call_args.kwargs['messages'][0]['content'])
            self.client.post(reverse('demo_chat'),{'industry':'automotive','handoff':token,'message':'Oil change'})
            self.assertNotIn('Alex',gateway.call_args.kwargs['messages'][0]['content'])

    def test_memory_endpoint_requires_csrf_and_post(self):
        call=self.guru()
        self.assertEqual(self.client.get(reverse('concierge_context',args=[call['id']])).status_code,405)
        self.assertEqual(self.post('concierge_context',{'visitor_name':'Alex'},[call['id']],Client(enforce_csrf_checks=True)).status_code,403)
