from unittest.mock import patch
from urllib.parse import urlparse

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assistant_ai.concierge_context import prompt as visitor_prompt
from core import cannabis_knowledge as knowledge
from core.demo_profiles import system_prompt


class CannabisReferenceTests(SimpleTestCase):
    def test_reference_integrity_and_voice_budget_include_long_handoff(self):
        data=knowledge.library()
        ids=[t['id'] for t in data['topics']]
        self.assertEqual(len(ids),len(set(ids)))
        for topic in data['topics']:
            self.assertTrue(topic['summary'] and topic['voice'] and topic['evidence'])
            self.assertTrue(topic['sources'])
            for source in topic['sources']:
                self.assertEqual(urlparse(data['sources'][source]['url']).scheme,'https')
        prompt=system_prompt({'slug':'cannabis','business':'Violet Leaf'})
        context=visitor_prompt({'visitor_name':'A'*60,'request_summary':'B'*500,'opening_question':'C'*240})
        self.assertLessEqual(len(prompt+context),10000)
        for topic in data['topics']:
            self.assertIn(topic['voice'],prompt)

    def test_specific_science_questions_find_relevant_evidence(self):
        cases={
            'Tell me about Dutch Treat':'named-strain-research',
            'What did the Blue Dream research find?':'named-strain-research',
            'What does the endocannabinoid system do?':'endocannabinoid-system',
            'Are terpenes proven medicines?':'terpenes-and-entourage',
            'Does CBD help chronic pain?':'chronic-pain',
            'How do I read a COA?':'lab-reports',
            'Can cannabis cure cancer?':'cancer-and-nausea',
            'What is the evidence for PTSD?':'ptsd',
            'What does delta-8 mean?':'delta8-and-novel-products',
        }
        for message,expected in cases.items():
            with self.subTest(message=message):
                topics=knowledge.topics_for(message)
                self.assertIn(expected,[t['id'] for t in topics])
                self.assertNotIn('can’t help select',knowledge.sample_answer(message))

    def test_unknown_strain_never_gets_an_invented_profile(self):
        answer=knowledge.sample_answer('Tell me about Galactic Pineapple 9000')
        self.assertIn('don’t have a verified reference',answer)
        self.assertNotIn('%',answer)
        answer=knowledge.sample_answer('What are the medicinal effects of Galactic Pineapple 9000 strain?')
        self.assertIn('not a complete strain registry',answer)
        self.assertNotIn('general business information',answer)

    def test_prior_topic_is_only_used_for_explicit_followups(self):
        history=[{'role':'user','content':'Tell me about Blue Dream'}]
        self.assertEqual(knowledge.topics_for('Tell me more',history)[0]['id'],'named-strain-research')
        self.assertEqual(knowledge.topics_for('Galactic Pineapple 9000',history),[])

    def test_general_medical_education_is_distinct_from_personal_treatment(self):
        education=knowledge.sample_answer('What are the medicinal benefits?')
        self.assertIn('Epidiolex',education)
        personal=knowledge.sample_answer('What dose helps pain?')
        self.assertIn('clinician or pharmacist',personal)
        self.assertIn('AHRQ',personal)
        cancer=knowledge.sample_answer('Does cannabis cure cancer?')
        self.assertIn('do not establish a cure',cancer)
        self.assertNotIn('buy',cancer)

    def test_emergency_exposure_takes_priority_over_educational_answer(self):
        answer=knowledge.sample_answer('My toddler ate a cannabis gummy')
        self.assertIn('1-800-222-1222',answer)
        self.assertIn('emergency',answer)
        self.assertNotIn('What would you',answer)


@override_settings(PLATFORM_OPENAI_API_KEY='')
class CannabisIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_fallback_returns_reading_links_and_retains_them_in_history(self):
        response=self.client.post(reverse('demo_chat'),{'industry':'cannabis','message':'What are terpenes?'}).json()
        self.assertEqual(response['mode'],'guided')
        self.assertIn('terpenes-and-entourage',response['knowledge_topics'])
        self.assertIn('aroma',response['reply'])
        turn=self.client.session['demo_history']['cannabis'][-1]
        self.assertEqual(turn['knowledge_topics'],response['knowledge_topics'])
        page=self.client.get(reverse('demo'))
        self.assertContains(page,'Cannabis knowledge &amp; sources')

    @override_settings(PLATFORM_OPENAI_API_KEY='test-only')
    def test_text_model_receives_references_without_extra_history_fields(self):
        url=reverse('demo_chat')
        with patch('core.demo_views.PlatformAIService.chat',return_value=('An educational answer',{'status':'success'})) as gateway:
            self.client.post(url,{'industry':'cannabis','message':'Explain terpenes'})
            self.client.post(url,{'industry':'cannabis','message':'Does CBD help pain?'})
        messages=gateway.call_args.kwargs['messages']
        self.assertIn('AHRQ',messages[0]['content'])
        self.assertIn('https://www.ncbi.nlm.nih.gov/books/NBK618045/',messages[0]['content'])
        for message in messages:
            self.assertEqual(set(message),{'role','content'})

    @override_settings(PLATFORM_OPENAI_API_KEY='test-only')
    def test_other_employee_does_not_receive_cannabis_reference(self):
        with patch('core.demo_views.PlatformAIService.chat',return_value=('A dining answer',{'status':'success'})) as gateway:
            response=self.client.post(reverse('demo_chat'),{'industry':'food-hospitality','message':'Do you have vegetarian options?'}).json()
        self.assertEqual(response['knowledge_topics'],[])
        self.assertNotIn('CURATED REFERENCE',gateway.call_args.kwargs['messages'][0]['content'])

    def test_public_library_shows_sources_and_filters_topics(self):
        url=reverse('cannabis_knowledge')
        page=self.client.get(url)
        self.assertContains(page,'26 reference topics')
        self.assertContains(page,'22 linked sources')
        self.assertContains(page,'https://www.ncbi.nlm.nih.gov/books/NBK618045/')
        filtered=self.client.get(url,{'q':'Blue Dream'})
        self.assertEqual([t['id'] for t in filtered.context['topics']],['named-strain-research'])
        unknown=self.client.get(url,{'q':'<script>alert(1)</script>'})
        self.assertNotContains(unknown,'<script>alert(1)</script>')
        self.assertContains(unknown,'No reviewed entry matches')

    def test_live_interface_exposes_library_without_starting_a_call(self):
        page=self.client.get(reverse('concierge'),{'industry':'cannabis','embed':'1'})
        self.assertContains(page,reverse('cannabis_knowledge'))
        self.assertContains(page,'The science, the strains, the evidence.')
