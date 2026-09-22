import io
import json
import uuid
import zipfile
from datetime import date
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Lead, LeadSheet, LeadGenerationBatch, LeadStaging
from .sheet_schema import columns
from .sheet_files import make_xlsx, read_file


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class LeadSheetTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.rep=User.objects.create_user(username='sheet-rep',role='employee')
        self.other=User.objects.create_user(username='other',role='employee')
        self.manager=User.objects.create_user(username='sheet-manager',role='owner')
        self.lead=Lead.objects.create(business_name='Sheet Plumbing',phone='(619) 555-0123',assigned_to=self.rep,assessment_brief={'meeting_url':'https://example.com/meeting'})
        self.other_lead=Lead.objects.create(business_name='Other private business',assigned_to=self.other)
        self.client_lead=Lead.objects.create(business_name='Client private business',lead_type='client_customer',assigned_to=self.rep)
        self.client.force_login(self.rep)

    def open(self, **query):
        response=self.client.get(reverse('lead_sheet_new'),query)
        self.assertEqual(response.status_code,200)
        return response.context['sheet_data']

    def payload(self,data,rows=None):
        return {'snapshot':data['snapshot'],'mutation_id':str(uuid.uuid4()),'title':'My prospect list','rows':rows if rows is not None else [{'key':r['key'],'changes':{}} for r in data['rows']]}

    def save(self,payload):
        return self.client.post(reverse('lead_sheet_save'),json.dumps(payload),content_type='application/json')

    def newrow(self,**values):return {'key':str(uuid.uuid4()),'changes':values}

    def test_blank_is_read_only_and_save_populates_crm(self):
        initial=Lead.objects.count();data=self.open()
        self.assertFalse(LeadSheet.objects.exists());self.assertEqual(Lead.objects.count(),initial)
        response=self.save(self.payload(data,[self.newrow(business_name='New Prospect',phone='+1 760 555 0105',follow_up_date='2026-10-04',goal='Fewer missed calls')]))
        self.assertEqual(response.status_code,200,response.content)
        lead=Lead.objects.get(business_name='New Prospect')
        self.assertEqual(lead.assigned_to,self.rep);self.assertEqual(lead.follow_up_date,date(2026,10,4))
        self.assertEqual(timezone.localtime(lead.next_follow_up_at).hour,9);self.assertIsNone(lead.last_contact_at)
        self.assertEqual(lead.assessment_brief['goal'],'Fewer missed calls')
        self.assertContains(self.client.get(reverse('sales_pipeline')),'New Prospect')
        self.assertEqual(lead.activities.get().activity_type,'manual_note')

    def test_scope_and_private_workbooks(self):
        data=self.open(source='all');self.assertEqual(len(data['rows']),1)
        self.assertEqual(self.client.get(reverse('lead_sheet_new'),{'source':'lead','record':self.other_lead.pk}).status_code,404)
        saved=self.save(self.payload(data)).json()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(saved['url']).status_code,404)
        self.assertEqual(self.client.get(saved['url']+'export/').status_code,404)
        self.assertEqual(self.save(self.payload(saved)).status_code,409)
        self.client.force_login(self.manager)
        self.assertEqual(len(self.open(source='all')['rows']),2)
        self.assertEqual(self.client.get(saved['url']).status_code,404)

    def test_update_preserves_unedited_fields_and_removal_keeps_record(self):
        data=self.open(source='lead',record=self.lead.pk)
        payload=self.payload(data);payload['rows'][0]['changes']={'notes':'Spoke with owner','workflow':'Manual intake'}
        response=self.save(payload);self.assertEqual(response.status_code,200,response.content)
        self.lead.refresh_from_db();self.assertEqual(self.lead.phone,'(619) 555-0123')
        self.assertEqual(self.lead.assessment_brief['meeting_url'],'https://example.com/meeting')
        self.assertIsNone(self.lead.last_contact_at)
        self.assertEqual(self.save(self.payload(response.json(),[])).status_code,200)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())
        self.assertEqual(LeadSheet.objects.get().rows,[])

    def test_atomic_validation_and_duplicate_detection(self):
        data=self.open();before=Lead.objects.count()
        result=self.save(self.payload(data,[self.newrow(business_name='Valid'),self.newrow(business_name='Invalid',email='not-email')]))
        self.assertEqual(result.status_code,400);self.assertEqual(Lead.objects.count(),before)
        result=self.save(self.payload(data,[self.newrow(business_name='Repeated A',phone='7605550100'),self.newrow(business_name='Repeated B',phone='+1 (760) 555-0100')]))
        self.assertEqual(result.status_code,400);self.assertEqual(Lead.objects.count(),before)
        self.lead.archived=True;self.lead.status='do_not_contact';self.lead.save()
        result=self.save(self.payload(data,[self.newrow(business_name='Do not clone',phone='16195550123')]))
        self.assertEqual(result.status_code,400);self.assertEqual(Lead.objects.count(),before)

    def test_conflicts_reassignment_and_idempotent_retry(self):
        data=self.open(source='all');payload=self.payload(data);payload['rows'][0]['changes']={'notes':'Old sheet'}
        Lead.objects.filter(pk=self.lead.pk).update(notes='Fresh CRM edit')
        self.assertEqual(self.save(payload).status_code,409)
        self.lead.refresh_from_db();self.assertEqual(self.lead.notes,'Fresh CRM edit')
        data=self.open(source='all');payload=self.payload(data);payload['rows'][0]['changes']={'notes':'Old sheet'}
        Lead.objects.filter(pk=self.lead.pk).update(assigned_to=self.other)
        self.assertEqual(self.save(payload).status_code,400)
        data=self.open();payload=self.payload(data,[self.newrow(business_name='Once only')])
        self.assertEqual(self.save(payload).status_code,200)
        self.assertEqual(self.save(payload).status_code,200)
        self.assertEqual(Lead.objects.filter(business_name='Once only').count(),1)
        payload['mutation_id']=str(uuid.uuid4());self.assertEqual(self.save(payload).status_code,409)

    def test_refresh_reads_live_values_and_unchanged_rows_do_not_overwrite(self):
        data=self.open(source='all');Lead.objects.filter(pk=self.lead.pk).update(notes='Latest')
        result=self.save(self.payload(data));self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['rows'][0]['values']['notes'],'Latest')
        Lead.objects.filter(pk=self.lead.pk).update(notes='Even newer')
        refreshed=self.client.get(result.json()['url']).context['sheet_data']
        self.assertEqual(refreshed['rows'][0]['values']['notes'],'Even newer')

    def test_status_assignment_and_unknown_field_guards(self):
        self.lead.status='do_not_contact';self.lead.save()
        data=self.open(source='all');payload=self.payload(data);payload['rows'][0]['changes']={'status':'new'}
        self.assertEqual(self.save(payload).status_code,400)
        payload['rows'][0]['changes']={'assigned_to':str(self.other.pk)};self.assertEqual(self.save(payload).status_code,400)
        payload['rows'][0]['changes']={'archived':'false'};self.assertEqual(self.save(payload).status_code,400)
        payload['rows'][0]['changes']={'notes':{'object':'invalid'}};self.assertEqual(self.save(payload).status_code,400)
        self.lead.status='new';self.lead.save();data=self.open(source='all')
        payload=self.payload(data);payload['rows'][0]['changes']={'status':'Appointment Scheduled'}
        self.assertEqual(self.save(payload).status_code,400)
        self.assertEqual(self.save(self.payload(self.open(),[self.newrow(business_name='Bad URL',website='javascript:alert(1)')])).status_code,400)

    def test_context_filters_and_links(self):
        self.lead.status='warm_lead';self.lead.save()
        self.assertEqual(len(self.open(source='pipeline',stage='new')['rows']),0)
        self.assertEqual(len(self.open(source='pipeline',stage='conversation')['rows']),1)
        response=self.client.get(reverse('lead_detail',args=[self.lead.pk]))
        self.assertContains(response,'Edit this view in a sheet')
        self.assertIn(f'record={self.lead.pk}',response.context['context_sheet_url'])
        for route in ['lead_upload','crm_home','sales_pipeline','sales_assessments','lead_finder']:
            self.assertContains(self.client.get(reverse(route)),'Blank lead sheet')

    def test_prospect_edits_stay_in_finder(self):
        batch=LeadGenerationBatch.objects.create(employee=self.rep,industry='HVAC')
        staging=LeadStaging.objects.create(batch=batch,created_by=self.rep,business_name='Finder Heating',phone_number='7605550110',industry='HVAC')
        data=self.open(source='finder',kind='prospects',finder_batch=batch.pk)
        payload=self.payload(data);payload['rows'][0]['changes']={'notes':'Owner is Alex','phone':'7605550111'}
        result=self.save(payload);self.assertEqual(result.status_code,200,result.content)
        staging.refresh_from_db();self.assertEqual(staging.notes,'Owner is Alex');self.assertEqual(staging.phone_number,'7605550111')
        self.assertFalse(Lead.objects.filter(business_name=staging.business_name).exists())
        self.client.force_login(self.other);self.assertEqual(len(self.open(source='finder',kind='prospects')['rows']),0)

    def test_excel_export_roundtrip_preserves_identity_and_safe_text(self):
        self.lead.notes='=DANGEROUS()';self.lead.phone='000123';self.lead.save()
        response=self.client.get(reverse('lead_sheet_export'),{'source':'all'})
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            sheet=zf.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('=DANGEROUS()',sheet);self.assertIn('000123',sheet);self.assertNotIn('<f>',sheet)
            self.assertIn('state="frozen"',sheet);self.assertIn('hidden="1"',sheet)
            self.assertIn('dataValidations',sheet)
        preview=self.client.post(reverse('lead_sheet_import'),{'file':SimpleUploadedFile('leads.xlsx',response.content)})
        self.assertEqual(preview.status_code,200,preview.content)
        data=preview.json();data['rows'][0]['changes']['business_name']='Renamed Plumbing'
        payload=self.payload(data,[{'key':r['key'],'changes':r['changes']} for r in data['rows']])
        saved=self.save(payload);self.assertEqual(saved.status_code,200,saved.content)
        self.lead.refresh_from_db();self.assertEqual(self.lead.business_name,'Renamed Plumbing');self.assertEqual(self.lead.phone,'000123')
        self.assertEqual(Lead.objects.filter(assigned_to=self.rep,lead_type='internal_sales').count(),1)
        stale=self.client.post(reverse('lead_sheet_import'),{'file':SimpleUploadedFile('old.xlsx',response.content)})
        self.assertEqual(stale.status_code,400)

    def test_template_and_csv_import_validation(self):
        raw=make_xlsx(columns(self.rep),[])
        parsed,warnings=read_file(SimpleUploadedFile('template.xlsx',raw),columns(self.rep))
        self.assertEqual(parsed,[])
        response=self.client.post(reverse('lead_sheet_import'),{'file':SimpleUploadedFile('list.csv',b'Company,Email,Phone,Follow-up date\nCSV Company,person@example.com,00123,2026-10-10\n')})
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();saved=self.save(self.payload(data,[{'key':r['key'],'changes':r['changes']} for r in data['rows']]))
        self.assertEqual(saved.status_code,200,saved.content);self.assertEqual(Lead.objects.get(business_name='CSV Company').phone,'00123')
        for name,content in [('bad.xlsx',b'notzip'),('old.xls',b'old'),('dup.csv',b'Business name,Company\nA,B')]:
            response=self.client.post(reverse('lead_sheet_import'),{'file':SimpleUploadedFile(name,content)})
            self.assertEqual(response.status_code,400)

    def test_malformed_requests_limits_and_csrf(self):
        for value in ('not json','[]','null'):
            self.assertEqual(self.client.post(reverse('lead_sheet_save'),value,content_type='application/json').status_code,400)
        data=self.open();payload=self.payload(data);payload['rows']=[self.newrow() for _ in range(501)]
        self.assertEqual(self.save(payload).status_code,400)
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.rep)
        self.assertEqual(client.post(reverse('lead_sheet_save'),json.dumps(self.payload(data)),content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.client.get(reverse('lead_sheets')).status_code,302)
        self.client.force_login(get_user_model().objects.create_user(username='customer',role='client'))
        self.assertEqual(self.client.get(reverse('lead_sheets')).status_code,302)
