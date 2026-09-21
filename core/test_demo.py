import json
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.cache import cache

from assistant_ai import concierge, demo_video
from assistant_ai.models import ConciergeCall, Conversation
from core.demo_profiles import profiles, resolve_profile, system_prompt
from core.industry_options import get_industry_options
from crm.models import Lead


@override_settings(PLATFORM_OPENAI_API_KEY="", RUNWAYML_API_SECRET="test-only", VIDEO_CONCIERGE_ENABLED=True)
class CategoryDemoTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_guru_and_every_demo_employee_share_voice_turn_controls(self):
        for query in [{}, *({"industry": p["slug"], "embed": "1"} for p in profiles())]:
            with self.subTest(query=query):
                page=self.client.get(reverse('concierge'),query)
                self.assertContains(page,'id="guideInterrupt"')
                self.assertContains(page,'id="guideMicBoost"')
                self.assertContains(page,'Interrupt &amp; speak')
                self.assertContains(page,'Your mic pauses during replies')
                self.assertContains(page,'js/concierge.js')
                self.assertContains(page,'js/concierge-call.js')

    def test_catalog_compresses_all_industries_into_thirteen_distinct_characters(self):
        entries=profiles()
        self.assertEqual(len(entries),13)
        self.assertEqual(len({p['character'] for p in entries}),13)
        slugs=[slug for item in entries for slug in item['industry_slugs']]
        options,_=get_industry_options()
        self.assertEqual(set(slugs),{i.slug for i in options})
        self.assertEqual(len(slugs),len(set(slugs)))
        self.assertEqual(resolve_profile('restaurant')['name'],'Sage')
        self.assertEqual(resolve_profile('catering')['name'],'Sage')
        self.assertEqual(resolve_profile('hotel')['name'],'Aria')
        self.assertIsNone(resolve_profile('not-real'))

    def test_text_chat_is_scoped_and_reset_leaves_other_category_intact(self):
        url=reverse('demo_chat')
        self.client.post(url,{'industry':'food-hospitality','message':'A table for four'})
        self.client.post(url,{'industry':'automotive','message':'Oil change'})
        self.assertEqual(len(self.client.session['demo_history']['food-hospitality']),2)
        self.client.post(url,{'industry':'food-hospitality','reset':'1'})
        self.assertNotIn('food-hospitality',self.client.session['demo_history'])
        self.assertIn('automotive',self.client.session['demo_history'])
        self.assertEqual(self.client.post(url,{'industry':'invalid','reset':'1'}).status_code,400)
        self.assertFalse(Lead.objects.exists());self.assertFalse(Conversation.objects.exists())

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only")
    def test_live_model_receives_only_selected_business_and_its_own_history(self):
        with patch('core.demo_views.PlatformAIService.chat',return_value=('A sample reply',{'status':'success'})) as gateway:
            url=reverse('demo_chat')
            self.client.post(url,{'industry':'food-hospitality','message':'Vegetarian dinner'})
            self.client.post(url,{'industry':'automotive','message':'Oil change'})
            response=self.client.post(url,{'industry':'food-hospitality','message':'For Friday'})
        self.assertEqual(response.json()['mode'],'ai')
        messages=gateway.call_args.kwargs['messages']
        self.assertIn('Sage & Ember',messages[0]['content'])
        self.assertIn('Vegetarian dinner',str(messages))
        self.assertNotIn('Oil change',str(messages))
        self.assertIn('never request real',messages[0]['content'])

    def test_anonymous_history_has_a_size_bound(self):
        for entry in profiles():
            self.client.post(reverse('demo_chat'),{'industry':entry['slug'],'message':'Hello'})
        self.assertEqual(len(self.client.session['demo_history']),8)

    def test_provider_configuration_and_secrets_are_not_in_public_page(self):
        page=self.client.get(reverse('demo'))
        self.assertEqual(len(page.context['demo_industries']),13)
        self.assertNotContains(page,'test-only')
        self.assertIn('no-store',page.headers['Cache-Control'])
        for item in page.context['demo_industries']:
            self.assertNotIn('facts',item);self.assertNotIn('escalation',item)

    def test_cannabis_has_its_own_employee_and_guru_introduction(self):
        profile=resolve_profile('cannabis')
        self.assertEqual(profile['name'],'MaryJain')
        self.assertEqual(set(profile['covers']),{'Dispensary','Cannabis Delivery','CBD Store'})
        for slug in profile['industry_slugs']:
            self.assertEqual(resolve_profile(slug)['name'],'MaryJain')
            self.assertNotIn(slug,resolve_profile('hospitality-retail')['industry_slugs'])
        self.assertIn('MaryJain',concierge.personality())
        introduction=next(tool for tool in concierge.tool_definitions() if tool['name']=='introduce_demo_employee')
        self.assertIn('cannabis',str(introduction))
        page=self.client.get(reverse('demo'),{'industry':'cannabis'})
        self.assertContains(page,'13 characters.')
        self.assertContains(page,'MaryJain')

    def test_cannabis_guided_preview_educates_without_arranging_purchases(self):
        url=reverse('demo_chat')
        hours=self.client.post(url,{'industry':'cannabis','message':'What are your hours?'}).json()
        self.assertEqual(hours['mode'],'guided')
        self.assertIn('Monday–Friday',hours['reply'])
        for message in ['Can I order for delivery tomorrow?', 'Which strain should I buy?']:
            with self.subTest(message=message):
                reply=self.client.post(url,{'industry':'cannabis','message':message}).json()['reply']
                self.assertIn('can’t help select, purchase or arrange delivery',reply)
                self.assertNotIn('preferred day or time',reply)
        education=self.client.post(url,{'industry':'cannabis','message':'What does research say about pain?'}).json()
        self.assertIn('AHRQ',education['reply'])
        self.assertIn('chronic-pain',education['knowledge_topics'])
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(Conversation.objects.exists())

    @override_settings(PLATFORM_OPENAI_API_KEY='test-only')
    def test_maryjain_ai_uses_the_educational_persona(self):
        with patch('core.demo_views.PlatformAIService.chat',return_value=('Our sample office hours are 9am–5pm.',{'status':'success'})) as gateway:
            response=self.client.post(reverse('demo_chat'),{'industry':'dispensary','message':'What are your hours?'})
        self.assertEqual(response.json()['industry'],'cannabis')
        prompt=gateway.call_args.kwargs['messages'][0]['content']
        self.assertIn('MaryJain',prompt)
        self.assertIn('Do not take, arrange or assist purchases or deliveries.',prompt)

    def test_demo_video_requires_allowlisted_category_and_consent(self):
        url=reverse('concierge_start')
        with patch('assistant_ai.demo_video.available_profiles',return_value={'food-hospitality'}),patch('assistant_ai.demo_video.create_session',return_value={'id':str(uuid.uuid4())}) as create:
            self.assertEqual(self.client.post(url,json.dumps({'industry':'food-hospitality'}),content_type='application/json').status_code,400)
            self.assertEqual(self.client.post(url,json.dumps({'industry':'unknown','consent':True}),content_type='application/json').status_code,400)
            response=self.client.post(url,json.dumps({'industry':'food-hospitality','consent':True}),content_type='application/json')
        self.assertEqual(response.status_code,201)
        self.assertEqual(create.call_args.args[0]['name'],'Sage')
        self.assertEqual(ConciergeCall.objects.count(),1)
        self.assertFalse(Lead.objects.exists())

    def test_saved_category_defaults_speed_up_calls_but_stale_defaults_get_overridden(self):
        profile=resolve_profile('food-hospitality');entry={'id':'test-avatar','ready':True}
        ready={'status':'READY','personality':system_prompt(profile),'startScript':profile['greeting']}
        with patch('assistant_ai.demo_video.manifest',return_value={profile['slug']:entry}),patch('assistant_ai.concierge.runway_request',side_effect=[ready,{'id':'session'}]) as api:
            demo_video.create_session(profile)
        payload=api.call_args.args[2]
        self.assertNotIn('personality',payload);self.assertEqual(payload['tools'],[])
        cache.clear()
        with patch('assistant_ai.demo_video.manifest',return_value={profile['slug']:entry}),patch('assistant_ai.concierge.runway_request',side_effect=[{}, {'id':'session'}]) as api:
            demo_video.create_session(profile)
        self.assertEqual(api.call_args.args[2]['personality'],system_prompt(profile))

    def test_guru_prompt_and_tool_schema_fit_provider_limits(self):
        self.assertLessEqual(len(concierge.personality()),10000)
        for tool in concierge.tool_definitions():
            self.assertLessEqual(len(tool['description']),1024)
            for parameter in tool.get('parameters',[]):
                self.assertLessEqual(len(parameter.get('enum',[])),20)
