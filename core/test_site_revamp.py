from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clients.models import AIInstance, ClientAccount, BusinessProfile
from crm.models import Lead


class ChatbotWorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('chat-preview', role='client')
        self.account = ClientAccount.objects.create(user=self.user, business_name='Sample Bakery', industry='Bakery')
        self.ai = AIInstance.objects.create_from_template(self.account)
        self.ai.openai_api_mode = 'fallback'
        self.ai.save()
        BusinessProfile.objects.create(client=self.account, hours='Monday–Friday, 9 AM–5 PM')
        self.client.force_login(self.user)

    def test_website_demo_intake_flows_into_private_workspace(self):
        self.assertFalse(self.ai.voice_enabled)
        self.assertFalse(self.ai.sms_enabled)
        self.assertEqual(self.ai.status, 'draft')
        self.assertIn('Website Chatbot', self.ai.name)
        response = self.client.post(reverse('widget_chat_api', args=[self.ai.slug]), {
            'message': 'What are your hours?', 'name': 'Jordan Example', 'phone': '760-555-0100',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('9 AM', response.json()['reply'])
        lead = Lead.objects.get(client=self.account)
        self.assertEqual(lead.name, 'Jordan Example')
        self.assertContains(self.client.get(reverse('client_leads')), 'Jordan Example')
        self.assertContains(self.client.get(reverse('client_conversations')), 'Jordan Example')
        self.assertEqual(self.client.get(reverse('client_leads_export')).status_code, 302)

    def test_demo_inbox_and_transcripts_stay_private(self):
        other = get_user_model().objects.create_user('other-preview', role='client')
        account = ClientAccount.objects.create(user=other, business_name='Other business')
        Lead.objects.create(client=account, lead_type='client_customer', name='Private Other Customer')
        Lead.objects.create(client=self.account, lead_type='internal_sales', name='Internal Sales Only')
        response = self.client.get(reverse('client_leads'))
        self.assertNotContains(response, 'Private Other Customer')
        self.assertNotContains(response, 'Internal Sales Only')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('client_leads')).status_code, 302)
        self.assertEqual(self.client.get(reverse('widget', args=[self.ai.slug])).status_code, 404)
