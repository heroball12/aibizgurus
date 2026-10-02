import json
from unittest.mock import patch

import httpx
from django.test import TestCase, override_settings
from openai import APIConnectionError, APITimeoutError, BadRequestError, PermissionDeniedError, RateLimitError

from .models import UsageRecord
from .provider_errors import provider_error_details
from .services import PlatformAIService, chat_sampling_options


def api_error(error_class, status, code=None, **extra):
    return error_class(
        'Private provider message sk-test-secret',
        response=httpx.Response(status, request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')),
        body={'code': code, 'message': 'Private prompt and sk-test-secret', **extra},
    )


@override_settings(PLATFORM_OPENAI_API_KEY='test-placeholder', OPENAI_DAILY_USAGE_LIMIT=0)
class ProviderErrorTests(TestCase):
    def test_strict_json_schema_reaches_provider(self):
        schema={'type':'object','properties':{},'required':[],'additionalProperties':False}
        with patch('assistant_ai.services.OpenAI') as sdk:
            response=sdk.return_value.chat.completions.create.return_value
            response.usage=None
            response.choices[0].message.content='{}'
            result,meta=PlatformAIService().structured_json(messages=[],model='gpt-5-mini',json_schema=schema)
        self.assertEqual((result,meta),({}, {'status':'success'}))
        self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs['response_format'], {'type':'json_schema','json_schema':{'name':'structured_reply','strict':True,'schema':schema}})

    def test_gpt5_mini_omits_unsupported_temperature_and_bounds_reasoning(self):
        service = PlatformAIService(assistant_role='sales_email')
        service.max_completion_tokens = 1300
        with patch('assistant_ai.services.OpenAI') as sdk:
            sdk.return_value.chat.completions.create.return_value.usage = None
            service.chat(messages=[], model='gpt-5-mini', temperature=.35)
        kwargs = sdk.return_value.chat.completions.create.call_args.kwargs
        self.assertNotIn('temperature', kwargs)
        self.assertEqual(kwargs['reasoning_effort'], 'minimal')
        self.assertEqual(kwargs['max_completion_tokens'], 1300)
        self.assertEqual(chat_sampling_options('gpt-5-mini-2025-08-07', .35), {'reasoning_effort':'minimal'})
        self.assertEqual(chat_sampling_options('gpt-4o-mini', .35), {'temperature':.35})

    def test_production_403_model_denial_is_classified_without_retrying(self):
        error = api_error(PermissionDeniedError, 403, 'model_not_found')
        service = PlatformAIService(assistant_role='sales_email')
        service.max_retries = 2
        with patch('assistant_ai.services.OpenAI') as sdk, self.assertLogs('assistant_ai.services', level='WARNING') as logs:
            sdk.return_value.chat.completions.create.side_effect = error
            content, meta = service.chat(messages=[{'role': 'user', 'content': 'Private prompt'}], fallback='unavailable')
        self.assertEqual(content, 'unavailable')
        self.assertEqual(meta['category'], 'model_access')
        self.assertEqual(meta['reason'], 'PermissionDeniedError')
        self.assertEqual(sdk.return_value.chat.completions.create.call_count, 1)
        record = UsageRecord.objects.get()
        self.assertEqual(record.metadata['provider_error']['http_status'], 403)
        self.assertEqual(record.metadata['provider_error']['provider_code'], 'model_not_found')
        recorded = json.dumps(record.metadata) + str(logs.output)
        for private in ['sk-test-secret', 'Private prompt', 'Private provider message']:
            self.assertNotIn(private, recorded)

    def test_quota_and_temporary_rate_limit_are_distinct(self):
        for code in ['insufficient_quota', 'project_spend_limit_exceeded', 'organization_usage_limit_exceeded']:
            self.assertEqual(provider_error_details(api_error(RateLimitError, 429, code))['category'], 'quota')
        self.assertEqual(provider_error_details(api_error(RateLimitError, 429, 'rate_limit_exceeded'))['category'], 'rate_limit')

    def test_transport_and_request_classification(self):
        request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')
        for error, category in [
            (APIConnectionError(request=request), 'connection'),
            (APITimeoutError(request=request), 'timeout'),
            (api_error(BadRequestError, 400, 'unsupported_parameter', param='temperature'), 'request'),
        ]:
            self.assertEqual(provider_error_details(error)['category'], category)

    def test_only_allowlisted_fields_are_recorded(self):
        error = api_error(PermissionDeniedError, 403, 'sk-private-code', param='private prompt', message='Missing scopes: model.request. Private details.')
        error.request_id = 'sk-private-request-id'
        self.assertEqual(provider_error_details(error), {'category': 'permission', 'http_status': 403, 'missing_model_request_scope': True})

    def test_transient_failure_can_retry_and_recover(self):
        service = PlatformAIService()
        with patch('assistant_ai.services.OpenAI') as sdk:
            response = sdk.return_value.chat.completions.create.return_value
            response.choices[0].message.content = 'Recovered'
            response.usage = None
            sdk.return_value.chat.completions.create.side_effect = [api_error(RateLimitError, 429, 'rate_limit_exceeded'), response]
            content, meta = service.chat(messages=[])
        self.assertEqual((content, meta), ('Recovered', {'status': 'success'}))
        self.assertEqual(UsageRecord.objects.get().status, 'success')
