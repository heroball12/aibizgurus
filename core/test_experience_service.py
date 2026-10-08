import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import DemoSession, DemoCRMLead, DemoCRMActivity, DemoRevision, DemoExperience
from core.experience import tools
from core.experience.service import public_order
from core.test_experience import completion
from crm.models import Lead


class ServiceExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_center', publish=True, stdout=StringIO())

    def setUp(self):
        response = self.client.post(reverse('experience_session'), '{}', content_type='application/json')
        self.session = DemoSession.objects.get(pk=response.json()['id'])
        self.crm_url = reverse('experience_crm') + '?session=' + str(self.session.pk)

    def api(self, action, client=None, **kwargs):
        return (client or self.client).post(reverse('experience_service'), json.dumps({
            'session': str(self.session.pk), 'action': action, **kwargs}), content_type='application/json')

    def intake(self, **overrides):
        return dict(name='Taylor Demo', phone='202-555-0146', email='taylor@example.com',
                    vehicle='2021 Honda CR-V', mileage=60000, services=['oil', 'brakes'],
                    concern='Oil change and a squeak when braking', visit_type='drop_off',
                    demo_acknowledged=True, **overrides)

    def submit(self, **kwargs):
        self.session.refresh_from_db()
        return self.api('submit', version=self.session.state.get('service_order', {}).get('version', 0),
                        fields=self.intake(), **kwargs)

    def staff(self, status, **changes):
        self.session.refresh_from_db()
        order = self.session.state['service_order']
        fields = dict(action='service_update', status=status, version=order['version'],
                      advisor=order['advisor'], technician=order.get('technician', ''), advisor_notes=order.get('advisor_notes', ''))
        fields.update(changes)
        response = self.client.post(self.crm_url, fields, follow=True)
        self.session.refresh_from_db()
        return response

    def test_form_to_booking_to_service_crm_and_full_order_lifecycle(self):
        slot = self.api('slots', day='Monday').json()['slots'][0]
        result = self.submit(slot_id=slot['id'])
        self.assertEqual(result.status_code, 200, result.content)
        order = result.json()['service_order']
        self.assertEqual(order['status'], 'scheduled')
        self.assertEqual(order['appointment']['id'], slot['id'])
        self.assertEqual(order['customer']['email'], 'taylor@example.com')
        lead = DemoCRMLead.objects.get(session=self.session)
        self.assertEqual(lead.assigned_to, 'Jordan Ellis · Service')
        self.assertEqual(lead.snapshot['service_order']['id'], order['id'])
        self.client.post(self.crm_url, {'action': 'signin'})
        page = self.client.get(self.crm_url)
        for text in ('Service desk', order['id'], 'Taylor Demo', '2021 Honda CR-V', 'Oil &amp; filter change'):
            self.assertContains(page, text)
        self.staff('checked_in')
        self.staff('inspection', technician='Casey Brooks', advisor_notes='Sample inspection: review requested maintenance with customer.')
        self.staff('awaiting_approval')
        denied = self.staff('in_progress')
        self.assertContains(denied, 'confirm simulated customer approval')
        self.assertEqual(self.session.state['service_order']['status'], 'awaiting_approval')
        self.staff('in_progress', approval_confirmed='on')
        self.assertTrue(self.session.state['service_order']['approval']['synthetic'])
        self.staff('ready')
        status = tools.execute(self.session, 'get_demo_service_status', {})['service_order']
        self.assertEqual(status['status_label'], 'Ready for pickup')
        self.assertEqual(status['id'], order['id'])
        self.staff('closed')
        self.assertEqual(self.session.state['appointments']['service']['status'], 'completed')
        self.assertEqual(DemoCRMLead.objects.count(), 1)
        self.assertFalse(Lead.objects.exists())
        self.assertTrue(DemoCRMActivity.objects.filter(action='Service order updated').exists())

    def test_validation_prevents_partial_or_cross_department_booking(self):
        bad = self.intake(); bad['phone'] = 'bad'; bad['services'] = ['not-a-service']
        self.assertEqual(self.api('submit', fields=bad, version=0).status_code, 400)
        bad = self.intake(); bad['demo_acknowledged'] = False
        self.assertEqual(self.api('submit', fields=bad, version=0).status_code, 400)
        bad = self.intake(); bad['vin'] = 'real-vin-not-accepted'
        self.assertEqual(self.api('submit', fields=bad, version=0).status_code, 400)
        self.assertEqual(self.submit(slot_id='invented').status_code, 400)
        sales = tools.execute(self.session, 'get_available_sales_slots', {'day': 'Monday'})['slots'][0]
        self.session.save()
        self.assertEqual(self.submit(slot_id=sales['id']).status_code, 400)
        self.session.refresh_from_db()
        self.assertNotIn('service_order', self.session.state)
        self.assertFalse(DemoCRMLead.objects.exists())

    def test_partial_ai_intake_unknown_fields_and_confirmed_booking_share_order(self):
        data = tools.execute(self.session, 'update_service_intake', {'vehicle': '2021 Honda CR-V', 'concern': 'Oil change', 'services': ['oil']})
        self.assertNotIn('error', data)
        self.assertNotIn('mileage', data['service_order'])
        self.assertEqual(data['service_order']['status'], 'intake')
        self.assertIn('error', tools.execute(self.session, 'update_service_intake', {'mileage': -1}))
        self.assertIn('error', tools.execute(self.session, 'update_service_intake', {}))
        self.assertIn('error', tools.execute(self.session, 'open_demo_service_intake', {'confirmed_by_customer': False}))
        self.assertNotIn('error', tools.execute(self.session, 'open_demo_service_intake', {'confirmed_by_customer': True}))
        order_id = self.session.state['service_order']['id']
        slot = tools.execute(self.session, 'get_service_slots', {'day': 'Monday'})['slots'][0]
        tools.execute(self.session, 'create_demo_service_appointment', {'slot_id': slot['id'], 'vehicle': '2021 Honda CR-V', 'request': 'Oil change', 'confirmed_by_customer': True})
        tools.sync_crm(self.session); self.session.save()
        self.assertEqual(public_order(self.session)['id'], order_id)
        self.assertEqual(public_order(self.session)['status'], 'scheduled')
        self.assertEqual(DemoCRMLead.objects.get().snapshot['service_order']['id'], order_id)

    def test_intake_edits_reschedule_same_order_and_do_not_duplicate(self):
        initial = self.submit().json()['service_order']
        slots = self.api('slots', day='Monday').json()['slots']
        scheduled = self.submit(slot_id=slots[0]['id']).json()['service_order']
        changed = self.submit(slot_id=slots[1]['id']).json()['service_order']
        self.assertEqual(initial['id'], changed['id'])
        self.assertEqual(changed['appointment']['id'], slots[1]['id'])
        count = DemoCRMActivity.objects.count()
        self.submit(slot_id=slots[1]['id'])
        self.assertEqual(count, DemoCRMActivity.objects.count())
        stale = self.api('submit', fields=self.intake(), version=scheduled['version'])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(DemoCRMLead.objects.count(), 1)

    def test_service_order_staff_permissions_transition_and_conflict_checks(self):
        self.submit()
        self.staff('checked_in')
        self.assertEqual(self.session.state['service_order']['status'], 'intake')
        self.client.post(self.crm_url, {'action': 'signin'})
        self.staff('ready')  # Cannot bypass inspection and approval.
        self.assertEqual(self.session.state['service_order']['status'], 'intake')
        self.staff('scheduled')  # No appointment exists.
        self.assertEqual(self.session.state['service_order']['status'], 'intake')
        self.staff('checked_in', version=0)
        self.assertEqual(self.session.state['service_order']['status'], 'intake')
        self.staff('checked_in')
        self.assertEqual(self.session.state['service_order']['status'], 'checked_in')
        self.assertEqual(self.submit().status_code, 409)
        self.assertIn('error', tools.execute(self.session, 'update_service_intake', {'concern': 'Overwrite repair'}))
        self.session.busy_until = timezone.now() + timedelta(seconds=60); self.session.save()
        self.staff('inspection')
        self.assertEqual(self.session.state['service_order']['status'], 'checked_in')
        self.assertEqual(self.api('open').status_code, 409)

    def test_cancelled_service_appointment_and_order_agree(self):
        slot = self.api('slots', day='Monday').json()['slots'][0]
        self.submit(slot_id=slot['id']); self.client.post(self.crm_url, {'action': 'signin'})
        self.staff('cancelled')
        self.assertEqual(public_order(self.session)['status'], 'cancelled')
        self.assertEqual(public_order(self.session)['appointment']['status'], 'cancelled')
        result = tools.execute(self.session, 'create_demo_service_appointment', {'slot_id': slot['id'], 'vehicle': '2021 Honda CR-V', 'request': 'Oil change', 'confirmed_by_customer': True})
        self.assertIn('error', result)

    def test_browser_isolation_expiration_reset_and_csrf(self):
        self.submit()
        self.assertEqual(self.api('open', client=Client()).status_code, 404)
        self.assertEqual(Client().get(self.crm_url).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        self.assertEqual(self.api('open', client=csrf).status_code, 403)
        self.client.post(reverse('experience_action'), json.dumps({'session': str(self.session.pk), 'action': 'reset'}), content_type='application/json')
        self.assertEqual(self.api('open').status_code, 404)
        self.assertFalse(DemoCRMLead.objects.exists())
        self.session.refresh_from_db(); self.assertEqual(self.session.state, {})

    @override_settings(PLATFORM_OPENAI_API_KEY='test-only')
    def test_spoken_conversation_tools_create_order_and_read_staff_status(self):
        with patch('assistant_ai.services.PlatformAIService.tool_completion', side_effect=[
            completion(calls=[('update_customer', {'name': 'Taylor Demo', 'phone': '202-555-0146', 'email': 'taylor@example.com'}),
                              ('update_service_intake', {'vehicle': '2021 Honda CR-V', 'services': ['oil'], 'concern': 'Oil change', 'mileage': 60000})]),
            completion('Your demo service intake is saved for Jordan. Would you prefer to drop off or wait?')]):
            response = self.client.post(reverse('experience_turn'), json.dumps({'session': str(self.session.pk), 'message': 'Use my sample information for an oil change.', 'mode': 'voice', 'request_id': str(uuid.uuid4())}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['service_order']['mileage'], 60000)
        self.assertEqual(response.json()['service_order']['customer']['name'], 'Taylor Demo')
        self.client.post(self.crm_url, {'action': 'signin'}); self.staff('checked_in')
        self.assertEqual(self.session.protocol, [])
        with patch('assistant_ai.services.PlatformAIService.tool_completion', side_effect=[completion(calls=[('get_demo_service_status', {})]), completion('Your demo vehicle is checked in with Jordan.')]):
            response = self.client.post(reverse('experience_turn'), json.dumps({'session': str(self.session.pk), 'message': 'What is my service status?', 'mode': 'voice', 'request_id': str(uuid.uuid4())}), content_type='application/json')
        self.assertEqual(response.json()['service_order']['status'], 'checked_in')

    def test_seed_upgrades_known_version_without_changing_historical_session(self):
        exp = DemoExperience.objects.get(slug='automotive')
        old = DemoRevision.objects.create(experience=exp, version='velocity-2026.1.2', content=exp.current_revision.content)
        exp.current_revision = old; exp.save()
        self.session.revision = old; self.session.save()
        call_command('seed_demo_center', stdout=StringIO())
        exp.refresh_from_db(); self.session.refresh_from_db()
        self.assertEqual(exp.current_revision.version, 'velocity-2026.1.3')
        self.assertEqual(self.session.revision_id, old.id)
