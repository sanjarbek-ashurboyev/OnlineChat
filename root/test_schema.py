"""The OpenAPI schema (/api/schema/) must describe what the API really does (Codex audit M-20)."""
import os
import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

# Login, refresh, logout and registration are for people without a (valid) access token.
PUBLIC = {'/api/v1/auth/login/', '/api/v1/auth/token/refresh/', '/api/v1/auth/logout/', '/api/v1/auth/register/'}


class SchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def component(self, name):
        return self.schema['components']['schemas'][name]

    def response(self, path, method, status):
        content = self.schema['paths'][path][method]['responses'][str(status)].get('content')
        return content and content['application/json']['schema']

    @staticmethod
    def ref(schema):
        # A read-only reference comes wrapped: {'allOf': [{'$ref': ...}], 'readOnly': True}.
        return schema.get('$ref') or schema.get('allOf', [{}])[0].get('$ref')

    def resolve(self, schema):
        ref = self.ref(schema)
        return self.component(ref.split('/')[-1]) if ref else schema

    def test_the_schema_generates_without_warnings_and_validates(self):
        # Each warning is a guess ("defaulting to string", "ignoring authenticator"). Fail on any.
        GENERATOR_STATS.reset()
        with tempfile.TemporaryDirectory() as folder:
            call_command('spectacular', '--fail-on-warn', '--validate', '--file', os.path.join(folder, 'schema.yml'))

    def test_every_endpoint_but_login_says_it_needs_a_token(self):
        self.assertIn('jwtAuth', self.schema['components'].get('securitySchemes', {}))
        for path, operations in self.schema['paths'].items():
            for method, operation in operations.items():
                with self.subTest(f'{method.upper()} {path}'):
                    if path in PUBLIC:
                        self.assertNotEqual(operation.get('security'), [{'jwtAuth': []}])
                    else:
                        self.assertEqual(operation.get('security'), [{'jwtAuth': []}])

    def test_a_chat_describes_its_participant_and_last_message(self):
        chat = self.component('Chat')['properties']
        self.assertEqual(self.ref(chat['participant']), '#/components/schemas/PublicUser')
        last_message = self.resolve(chat['last_message'])
        self.assertTrue(chat['last_message'].get('nullable') or last_message.get('nullable'))
        self.assertEqual(last_message['properties']['text']['type'], 'string')
        self.assertEqual(last_message['properties']['created_at']['format'], 'date-time')

    def test_is_online_is_a_boolean(self):
        self.assertEqual(self.component('PublicUser')['properties']['is_online']['type'], 'boolean')

    def test_starting_a_chat_returns_the_chat(self):
        # The view answers with ChatSerializer; the schema said ChatCreate, an object with no readable fields.
        self.assertEqual(self.ref(self.response('/api/v1/chats/', 'post', 201)), '#/components/schemas/Chat')

    def test_marking_read_returns_how_many_were_marked(self):
        body = self.resolve(self.response('/api/v1/chats/{chat_id}/read/', 'post', 200))
        self.assertEqual(body['properties']['marked_read']['type'], 'integer')

    def test_history_is_described_as_cursor_pages(self):
        # History has no `count` and no `?page=`; it pages by `?cursor=` (decision 009).
        path = '/api/v1/chats/{chat_id}/messages/'
        page = self.resolve(self.response(path, 'get', 200))
        self.assertNotIn('count', page['properties'])
        parameters = {p['name'] for p in self.schema['paths'][path]['get']['parameters']}
        self.assertIn('cursor', parameters)
        self.assertNotIn('page', parameters)

    def test_an_avatar_is_uploaded_as_a_file_and_returned_as_a_link(self):
        request = self.schema['paths']['/api/v1/auth/profile/']['patch']['requestBody']['content']
        sent = self.resolve(request['multipart/form-data']['schema'])['properties']['avatar']
        returned = self.resolve(self.response('/api/v1/auth/profile/', 'patch', 200))['properties']['avatar']
        self.assertEqual(sent['format'], 'binary')
        self.assertEqual(returned['format'], 'uri')
