import os
import tempfile
import unittest
from unittest.mock import patch


if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-cloudflare-channels-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')
if 'SECRET_KEY' not in os.environ:
    os.environ['SECRET_KEY'] = 'test-secret-key'

import web_outlook_app


class CloudflareChannelTestCase(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM account_tags')
            db.execute('DELETE FROM temp_email_tags')
            db.execute('DELETE FROM tags')
            db.execute('DELETE FROM temp_email_messages')
            db.execute('DELETE FROM temp_emails')
            db.execute('DELETE FROM cloudflare_channels')
            db.execute("UPDATE settings SET value = '' WHERE key IN ('cloudflare_worker_domain', 'cloudflare_email_domains', 'cloudflare_admin_password')")
            db.execute("UPDATE settings SET value = '' WHERE key LIKE 'cloudflare_ai_username_%'")
            db.commit()

    def create_channel(self, name='cfmail-us', enabled=True, is_default=False):
        with self.app.app_context():
            channel_id, error = web_outlook_app.create_cloudflare_channel(
                name=name,
                worker_domain=f'{name}.example.workers.dev',
                email_domains=f'{name}.example.com, alt-{name}.example.com',
                admin_password=f'{name}-admin',
                enabled=enabled,
                is_default=is_default,
            )
            self.assertIsNone(error)
            self.assertIsNotNone(channel_id)
            return channel_id

    def create_tag(self, name='cf-batch', color='#3366ff'):
        with self.app.app_context():
            tag_id = web_outlook_app.add_tag(name, color)
            self.assertIsNotNone(tag_id)
            return tag_id


class CloudflareChannelMigrationTests(CloudflareChannelTestCase):
    def test_init_db_migrates_legacy_settings_and_existing_temp_emails(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            web_outlook_app.set_setting('cloudflare_worker_domain', 'legacy-worker.example.workers.dev')
            web_outlook_app.set_setting('cloudflare_email_domains', 'legacy.example.com, legacy-alt.example.com')
            web_outlook_app.set_setting('cloudflare_admin_password', 'legacy-admin-password')
            self.assertTrue(web_outlook_app.add_temp_email(
                'legacy@legacy.example.com',
                provider='cloudflare',
                cloudflare_jwt='legacy-jwt',
                cloudflare_address_id='legacy-address-id',
            ))

            web_outlook_app.init_db()

            channels = web_outlook_app.list_cloudflare_channels(include_disabled=True)
            self.assertEqual(len(channels), 1)
            channel = channels[0]
            self.assertTrue(channel['is_default'])
            self.assertEqual(channel['worker_domain'], 'legacy-worker.example.workers.dev')
            self.assertEqual(channel['email_domains'], ['legacy.example.com', 'legacy-alt.example.com'])
            self.assertTrue(channel['admin_password_configured'])

            raw_password = db.execute(
                'SELECT admin_password FROM cloudflare_channels WHERE id = ?',
                (channel['id'],)
            ).fetchone()['admin_password']
            self.assertNotEqual(raw_password, 'legacy-admin-password')
            self.assertEqual(web_outlook_app.decrypt_data(raw_password), 'legacy-admin-password')

            temp_email = web_outlook_app.get_temp_email_by_address('legacy@legacy.example.com')
            self.assertEqual(temp_email['cloudflare_channel_id'], channel['id'])

            web_outlook_app.init_db()
            count = db.execute('SELECT COUNT(*) AS count FROM cloudflare_channels').fetchone()['count']
            self.assertEqual(count, 1)

    def test_init_db_migrates_legacy_settings_without_email_domains(self):
        with self.app.app_context():
            web_outlook_app.set_setting('cloudflare_worker_domain', 'legacy-worker.example.workers.dev')
            web_outlook_app.set_setting('cloudflare_email_domains', '')
            web_outlook_app.set_setting('cloudflare_admin_password', 'legacy-admin-password')
            self.assertTrue(web_outlook_app.add_temp_email(
                'legacy@unknown.example.com',
                provider='cloudflare',
                cloudflare_jwt='legacy-jwt',
                cloudflare_address_id='legacy-address-id',
            ))

            web_outlook_app.init_db()

            channels = web_outlook_app.list_cloudflare_channels(include_disabled=True)
            self.assertEqual(len(channels), 1)
            channel = channels[0]
            self.assertTrue(channel['is_default'])
            self.assertEqual(channel['email_domains'], [])
            self.assertEqual(
                web_outlook_app.get_temp_email_by_address('legacy@unknown.example.com')['cloudflare_channel_id'],
                channel['id'],
            )

    def test_init_db_deduplicates_legacy_case_conflicting_channel_names(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute('DROP INDEX IF EXISTS idx_cloudflare_channels_name_lower')
            db.execute(
                '''
                INSERT INTO cloudflare_channels
                (name, worker_domain, admin_password, enabled, is_default)
                VALUES (?, ?, ?, 1, 1)
                ''',
                ('CfMail', 'cfmail.example.workers.dev', web_outlook_app.encrypt_data('admin-secret'))
            )
            db.execute(
                '''
                INSERT INTO cloudflare_channels
                (name, worker_domain, admin_password, enabled, is_default)
                VALUES (?, ?, ?, 1, 0)
                ''',
                ('cfmail', 'cfmail-alt.example.workers.dev', web_outlook_app.encrypt_data('admin-secret'))
            )
            db.commit()

            web_outlook_app.init_db()

            channels = web_outlook_app.list_cloudflare_channels(include_disabled=True)
            names = [channel['name'] for channel in channels]
            normalized_names = [name.lower() for name in names]
            self.assertEqual(len(normalized_names), len(set(normalized_names)))
            self.assertIn('CfMail', names)
            self.assertTrue(any(name.startswith('cfmail-') for name in names))
            indexes = [
                row['name']
                for row in db.execute('PRAGMA index_list(cloudflare_channels)').fetchall()
            ]
            self.assertIn('idx_cloudflare_channels_name_lower', indexes)

    def test_init_db_does_not_create_empty_default_channel(self):
        with self.app.app_context():
            web_outlook_app.init_db()
            channels = web_outlook_app.list_cloudflare_channels(include_disabled=True)
            self.assertEqual(channels, [])


class CloudflareChannelApiTests(CloudflareChannelTestCase):
    def test_channel_email_domains_are_optional(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            column = next(
                row for row in db.execute('PRAGMA table_info(cloudflare_channels)').fetchall()
                if row['name'] == 'email_domains'
            )
            self.assertEqual(column['notnull'], 0)

        create_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'cfmail-no-domain',
            'worker_domain': 'cfmail-no-domain.example.workers.dev',
            'admin_password': 'admin-secret',
        })
        self.assertEqual(create_response.status_code, 200)
        create_payload = create_response.get_json()
        self.assertTrue(create_payload['success'])
        self.assertEqual(create_payload['channel']['email_domains'], [])

        channel_id = create_payload['channel']['id']
        domains_response = self.client.get(f'/api/cloudflare/domains?channel_id={channel_id}')
        self.assertEqual(domains_response.status_code, 200)
        domains_payload = domains_response.get_json()
        self.assertTrue(domains_payload['success'])
        self.assertEqual(domains_payload['domains'], [])

    def test_channel_name_is_case_insensitive_unique(self):
        create_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'CfMail',
            'worker_domain': 'cfmail.example.workers.dev',
            'admin_password': 'admin-secret',
        })
        self.assertTrue(create_response.get_json()['success'])
        channel_id = create_response.get_json()['channel']['id']

        duplicate_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'cfmail',
            'worker_domain': 'other.example.workers.dev',
            'admin_password': 'other-secret',
        })
        duplicate_payload = duplicate_response.get_json()
        self.assertFalse(duplicate_payload['success'])
        self.assertIn('名称已存在', duplicate_payload['error'])

        other_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'other',
            'worker_domain': 'other.example.workers.dev',
            'admin_password': 'other-secret',
        })
        self.assertTrue(other_response.get_json()['success'])
        other_id = other_response.get_json()['channel']['id']

        update_response = self.client.put(f'/api/cloudflare/channels/{other_id}', json={
            'name': 'CFMAIL',
            'worker_domain': 'other.example.workers.dev',
        })
        update_payload = update_response.get_json()
        self.assertFalse(update_payload['success'])
        self.assertIn('名称已存在', update_payload['error'])

        keep_case_response = self.client.put(f'/api/cloudflare/channels/{channel_id}', json={
            'name': 'cfmail',
            'worker_domain': 'cfmail.example.workers.dev',
        })
        self.assertTrue(keep_case_response.get_json()['success'])

        with self.app.app_context():
            db = web_outlook_app.get_db()
            indexes = [
                row['name']
                for row in db.execute('PRAGMA index_list(cloudflare_channels)').fetchall()
            ]
            self.assertIn('idx_cloudflare_channels_name_lower', indexes)

    def test_channel_crud_and_deletion_protection(self):
        create_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'cfmail-us',
            'worker_domain': 'cfmail-us.example.workers.dev',
            'email_domains': 'us.example.com, alt-us.example.com',
            'admin_password': 'admin-secret',
            'is_default': True,
        })
        self.assertEqual(create_response.status_code, 200)
        create_payload = create_response.get_json()
        self.assertTrue(create_payload['success'])
        channel_id = create_payload['channel']['id']
        self.assertNotIn('admin_password', create_payload['channel'])
        self.assertTrue(create_payload['channel']['admin_password_configured'])

        duplicate_response = self.client.post('/api/cloudflare/channels', json={
            'name': 'cfmail-us',
            'worker_domain': 'other.example.workers.dev',
            'email_domains': 'other.example.com',
            'admin_password': 'other-secret',
        })
        self.assertFalse(duplicate_response.get_json()['success'])

        update_response = self.client.put(f'/api/cloudflare/channels/{channel_id}', json={
            'name': 'cfmail-us',
            'worker_domain': 'cfmail-us-updated.example.workers.dev',
            'email_domains': 'updated.example.com',
            'enabled': False,
            'is_default': True,
        })
        self.assertEqual(update_response.status_code, 200)
        update_payload = update_response.get_json()
        self.assertTrue(update_payload['success'])
        self.assertFalse(update_payload['channel']['enabled'])

        with self.app.app_context():
            channel = web_outlook_app.get_cloudflare_channel_by_id(
                channel_id,
                include_disabled=True,
                include_secret=True,
            )
            self.assertEqual(web_outlook_app.decrypt_data(channel['admin_password']), 'admin-secret')
            self.assertTrue(web_outlook_app.add_temp_email(
                'bound@updated.example.com',
                provider='cloudflare',
                cloudflare_jwt='bound-jwt',
                cloudflare_address_id='bound-address-id',
                cloudflare_channel_id=channel_id,
            ))

        delete_response = self.client.delete(f'/api/cloudflare/channels/{channel_id}')
        delete_payload = delete_response.get_json()
        self.assertFalse(delete_payload['success'])
        self.assertIn('引用', delete_payload['error'])

        domains_response = self.client.get(f'/api/cloudflare/domains?channel_id={channel_id}')
        domains_payload = domains_response.get_json()
        self.assertFalse(domains_payload['success'])
        self.assertIn('不可用', domains_payload['error'])


class CloudflareChannelGlobalMailTests(CloudflareChannelTestCase):
    def test_cloudflare_messages_requires_valid_enabled_channel(self):
        unknown_response = self.client.get('/api/cloudflare/messages?channel_id=99999')
        self.assertEqual(unknown_response.status_code, 404)
        self.assertFalse(unknown_response.get_json()['success'])

        disabled_channel_id = self.create_channel(name='cfmail-disabled', enabled=False)
        disabled_response = self.client.get(f'/api/cloudflare/messages?channel_id={disabled_channel_id}')
        self.assertEqual(disabled_response.status_code, 400)
        self.assertFalse(disabled_response.get_json()['success'])

    def test_cloudflare_messages_uses_default_channel_when_channel_id_missing(self):
        default_channel_id = self.create_channel(name='cfmail-default', enabled=True, is_default=True)
        other_channel_id = self.create_channel(name='cfmail-other', enabled=True)

        with self.app.app_context():
            default_channel = web_outlook_app.get_cloudflare_channel_by_id(default_channel_id)

        with patch.object(web_outlook_app, 'cloudflare_get_admin_messages', return_value={
            'success': True,
            'messages': [],
            'count': 0,
        }) as cloudflare_mock:
            response = self.client.get('/api/cloudflare/messages?limit=20&offset=0')

        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['channel_id'], default_channel_id)
        self.assertEqual(payload['channel_name'], 'cfmail-default')
        self.assertEqual(cloudflare_mock.call_args.kwargs['channel']['id'], default_channel['id'])
        self.assertNotEqual(cloudflare_mock.call_args.kwargs['channel']['id'], other_channel_id)

    def test_cloudflare_messages_query_only_selected_channel(self):
        channel_id = self.create_channel(name='cfmail-us', enabled=True)
        other_channel_id = self.create_channel(name='cfmail-hk', enabled=True)
        raw_message = (
            "From: Sender <sender@example.com>\r\n"
            "To: user@googlemail.com\r\n"
            "Subject: Googlemail code\r\n"
            "\r\n"
            "Your code is 654321"
        )

        with self.app.app_context():
            selected_channel = web_outlook_app.get_cloudflare_channel_by_id(channel_id)

        with patch.object(web_outlook_app, 'cloudflare_get_admin_messages', side_effect=[
            {'success': True, 'messages': [], 'count': 0},
            {
                'success': True,
                'messages': [{
                    'id': 456,
                    'address': 'user@googlemail.com',
                    'raw': raw_message,
                }],
                'count': 1,
            },
        ]) as cloudflare_mock:
            response = self.client.get(
                f'/api/cloudflare/messages?channel_id={channel_id}&address=user@gmail.com&limit=20&offset=0'
            )

        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['channel_id'], channel_id)
        self.assertEqual(payload['channel_name'], 'cfmail-us')
        self.assertEqual(payload['queried_email'], 'user@googlemail.com')
        self.assertTrue(payload['fallback_used'])
        self.assertEqual(payload['emails'][0]['to'], 'user@googlemail.com')
        self.assertEqual(
            [call.kwargs['address'] for call in cloudflare_mock.call_args_list],
            ['user@gmail.com', 'user@googlemail.com']
        )
        self.assertEqual(
            [call.kwargs['channel']['id'] for call in cloudflare_mock.call_args_list],
            [selected_channel['id'], selected_channel['id']]
        )
        self.assertNotIn(other_channel_id, [call.kwargs['channel']['id'] for call in cloudflare_mock.call_args_list])


class CloudflareBatchGenerationTests(CloudflareChannelTestCase):
    def test_batch_generate_validates_count_channel_and_reports_failures(self):
        channel_id = self.create_channel(name='cfmail-us', enabled=True, is_default=True)
        disabled_channel_id = self.create_channel(name='cfmail-disabled', enabled=False)

        invalid_response = self.client.post('/api/temp-emails/generate-batch', json={
            'provider': 'cloudflare',
            'channel_id': channel_id,
            'domain': 'cfmail-us.example.com',
            'count': 0,
        })
        invalid_payload = invalid_response.get_json()
        self.assertFalse(invalid_payload['success'])
        self.assertIn('数量', invalid_payload['error'])

        disabled_response = self.client.post('/api/temp-emails/generate-batch', json={
            'provider': 'cloudflare',
            'channel_id': disabled_channel_id,
            'domain': 'cfmail-disabled.example.com',
            'count': 1,
        })
        disabled_payload = disabled_response.get_json()
        self.assertFalse(disabled_payload['success'])
        self.assertIn('不可用', disabled_payload['error'])

        create_results = [
            {'address': 'one@cfmail-us.example.com', 'jwt': 'jwt-one', 'id': 'addr-one'},
            {'success': False, 'error': 'upstream failed'},
            {'address': 'three@cfmail-us.example.com', 'jwt': 'jwt-three', 'id': 'addr-three'},
        ]
        with patch.object(web_outlook_app, 'cloudflare_create_address', side_effect=create_results) as create_mock:
            response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-us.example.com',
                'count': 3,
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['created_count'], 2)
        self.assertEqual(payload['failed_count'], 1)
        self.assertEqual(payload['emails'], ['one@cfmail-us.example.com', 'three@cfmail-us.example.com'])
        self.assertIn('upstream failed', payload['failures'][0]['error'])
        self.assertEqual(create_mock.call_count, 3)

        with self.app.app_context():
            one = web_outlook_app.get_temp_email_by_address('one@cfmail-us.example.com')
            three = web_outlook_app.get_temp_email_by_address('three@cfmail-us.example.com')
            self.assertEqual(one['cloudflare_channel_id'], channel_id)
            self.assertEqual(three['cloudflare_channel_id'], channel_id)

        with patch.object(web_outlook_app, 'cloudflare_create_address', return_value={'success': False, 'error': 'all failed'}):
            all_failed_response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-us.example.com',
                'count': 2,
            })
        all_failed_payload = all_failed_response.get_json()
        self.assertFalse(all_failed_payload['success'])
        self.assertEqual(all_failed_payload['created_count'], 0)
        self.assertEqual(all_failed_payload['failed_count'], 2)
        self.assertIn('all failed', all_failed_payload['error'])

    def test_batch_generate_binds_existing_tags_and_ignores_unknown_tags(self):
        channel_id = self.create_channel(name='cfmail-tags', enabled=True, is_default=True)
        tag_id = self.create_tag(name='批量标签')

        with patch.object(web_outlook_app, 'cloudflare_create_address', return_value={
            'address': 'tagged@cfmail-tags.example.com',
            'jwt': 'jwt-tagged',
            'id': 'addr-tagged',
        }):
            response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-tags.example.com',
                'count': 1,
                'tag_ids': [tag_id, 999999, 'bad'],
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['tagged_count'], 1)

        with self.app.app_context():
            temp_email = web_outlook_app.get_temp_email_by_address('tagged@cfmail-tags.example.com')
            tags = web_outlook_app.get_temp_email_tags(temp_email['id'])
            self.assertEqual([tag['id'] for tag in tags], [tag_id])

    def test_batch_generate_uses_explicit_usernames_in_order(self):
        channel_id = self.create_channel(name='cfmail-explicit', enabled=True, is_default=True)
        used_usernames = []

        def fake_create(username=None, domain=None, channel=None):
            used_usernames.append(username)
            return {
                'address': f'{username}@cfmail-explicit.example.com',
                'jwt': f'jwt-{username}',
                'id': f'id-{username}',
            }

        with patch.object(web_outlook_app, 'cloudflare_create_address', side_effect=fake_create) as create_mock:
            response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-explicit.example.com',
                'count': 3,
                'usernames': ['first', 'second@example.com', 'third.name'],
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['emails'], [
            'first@cfmail-explicit.example.com',
            'second@cfmail-explicit.example.com',
            'thirdname@cfmail-explicit.example.com',
        ])
        self.assertEqual(used_usernames, ['first', 'second', 'thirdname'])
        self.assertEqual(create_mock.call_count, 3)

        with self.app.app_context():
            saved = web_outlook_app.get_temp_email_by_address('second@cfmail-explicit.example.com')
            self.assertEqual(saved['provider'], 'cloudflare')
            self.assertEqual(saved['cloudflare_channel_id'], channel_id)

    def test_batch_generate_rejects_invalid_explicit_username_lists_before_create(self):
        channel_id = self.create_channel(name='cfmail-invalid', enabled=True, is_default=True)
        cases = [
            ({'count': 2, 'usernames': ['alpha']}, '数量'),
            ({'count': 1, 'usernames': ['alpha', 'beta']}, '数量'),
            ({'count': 2, 'usernames': ['dupe', 'du.pe']}, '重复'),
            ({'count': 1, 'usernames': ['!!']}, '格式'),
        ]

        for overrides, expected_error in cases:
            with self.subTest(overrides=overrides):
                with patch.object(web_outlook_app, 'cloudflare_create_address') as create_mock:
                    response = self.client.post('/api/temp-emails/generate-batch', json={
                        'provider': 'cloudflare',
                        'channel_id': channel_id,
                        'domain': 'cfmail-invalid.example.com',
                        **overrides,
                    })

                payload = response.get_json()
                self.assertFalse(payload['success'], payload)
                self.assertIn(expected_error, payload['error'])
                create_mock.assert_not_called()

    def test_batch_generate_random_usernames_without_implicit_ai(self):
        channel_id = self.create_channel(name='cfmail-random', enabled=True, is_default=True)
        self.client.put('/api/settings', json={
            'cloudflare_ai_username_enabled': True,
            'cloudflare_ai_username_api_url': 'https://ai.example.com/v1',
            'cloudflare_ai_username_model': 'gpt-test',
            'cloudflare_ai_username_api_key': 'secret-key',
            'cloudflare_ai_username_prompt': 'Generate {count} names with {seed}',
        })
        used_usernames = []

        def fake_create(username=None, domain=None, channel=None):
            used_usernames.append(username)
            return {
                'address': f'{username}@cfmail-random.example.com',
                'jwt': f'jwt-{username}',
                'id': f'id-{username}',
            }

        with patch.object(web_outlook_app, 'request_cloudflare_ai_usernames') as ai_mock, \
                patch.object(web_outlook_app, 'generate_random_temp_name', side_effect=['randomone', 'randomtwo']), \
                patch.object(web_outlook_app, 'cloudflare_create_address', side_effect=fake_create):
            response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-random.example.com',
                'count': 2,
                'usernames': [],
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(used_usernames, ['randomone', 'randomtwo'])
        ai_mock.assert_not_called()

    def test_batch_generate_partial_failure_includes_explicit_username_details(self):
        channel_id = self.create_channel(name='cfmail-partial', enabled=True, is_default=True)
        create_results = [
            {'address': 'alpha@cfmail-partial.example.com', 'jwt': 'jwt-alpha', 'id': 'addr-alpha'},
            {'success': False, 'error': 'upstream rejected'},
            {'address': 'gamma@cfmail-partial.example.com', 'id': 'addr-gamma'},
        ]

        with patch.object(web_outlook_app, 'cloudflare_create_address', side_effect=create_results):
            response = self.client.post('/api/temp-emails/generate-batch', json={
                'provider': 'cloudflare',
                'channel_id': channel_id,
                'domain': 'cfmail-partial.example.com',
                'count': 3,
                'usernames': ['alpha', 'beta', 'gamma'],
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['emails'], ['alpha@cfmail-partial.example.com'])
        self.assertEqual(payload['created_count'], 1)
        self.assertEqual(payload['failed_count'], 2)
        self.assertEqual([failure['username'] for failure in payload['failures']], ['beta', 'gamma'])
        self.assertIn('upstream rejected', payload['failures'][0]['error'])
        self.assertIn('返回数据不完整', payload['failures'][1]['error'])


class FakeOpenAIResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class CloudflareAiUsernameTests(CloudflareChannelTestCase):
    def enable_saved_ai_username_config(self):
        response = self.client.put('/api/settings', json={
            'cloudflare_ai_username_enabled': True,
            'cloudflare_ai_username_api_url': 'https://ai.example.com/v1',
            'cloudflare_ai_username_model': 'gpt-test',
            'cloudflare_ai_username_api_key': 'secret-key',
            'cloudflare_ai_username_prompt': 'Generate {count} names with {seed}',
        })
        self.assertTrue(response.get_json()['success'], response.get_json())

    def test_ai_username_settings_encrypt_mask_preserve_and_clear_api_key(self):
        update_response = self.client.put('/api/settings', json={
            'cloudflare_ai_username_enabled': True,
            'cloudflare_ai_username_api_url': 'https://ai.example.com/v1',
            'cloudflare_ai_username_model': 'gpt-test',
            'cloudflare_ai_username_api_key': 'secret-key',
            'cloudflare_ai_username_prompt': 'Generate {count} names with {seed}',
        })
        update_payload = update_response.get_json()
        self.assertTrue(update_payload['success'], update_payload)

        with self.app.app_context():
            raw_key = web_outlook_app.get_setting('cloudflare_ai_username_api_key')
            self.assertNotEqual(raw_key, 'secret-key')
            self.assertEqual(web_outlook_app.get_setting_decrypted('cloudflare_ai_username_api_key'), 'secret-key')

        settings_response = self.client.get('/api/settings')
        settings = settings_response.get_json()['settings']
        self.assertEqual(settings['cloudflare_ai_username_enabled'], 'true')
        self.assertEqual(settings['cloudflare_ai_username_api_url'], 'https://ai.example.com/v1')
        self.assertEqual(settings['cloudflare_ai_username_model'], 'gpt-test')
        self.assertTrue(settings['cloudflare_ai_username_api_key_configured'])
        self.assertNotEqual(settings.get('cloudflare_ai_username_api_key'), 'secret-key')

        preserve_response = self.client.put('/api/settings', json={
            'cloudflare_ai_username_api_url': 'https://ai2.example.com/v1',
            'cloudflare_ai_username_api_key': '',
        })
        self.assertTrue(preserve_response.get_json()['success'], preserve_response.get_json())
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting_decrypted('cloudflare_ai_username_api_key'), 'secret-key')

        clear_response = self.client.put('/api/settings', json={
            'cloudflare_ai_username_clear_api_key': True,
        })
        self.assertTrue(clear_response.get_json()['success'], clear_response.get_json())
        with self.app.app_context():
            self.assertEqual(web_outlook_app.get_setting_decrypted('cloudflare_ai_username_api_key'), '')

        settings_response = self.client.get('/api/settings')
        self.assertFalse(settings_response.get_json()['settings']['cloudflare_ai_username_api_key_configured'])

    def test_ai_username_test_endpoint_success_missing_config_and_upstream_failure(self):
        success_payload = {
            'choices': [{
                'message': {
                    'content': '["Acme.Sales", "john@example.com", "bad!!", "AcmeSales"]'
                }
            }]
        }
        with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(payload=success_payload)) as post_mock:
            response = self.client.post('/api/cloudflare/ai-usernames/test', json={
                'api_url': 'https://ai.example.com/v1',
                'model': 'gpt-test',
                'api_key': 'secret-key',
                'prompt': 'Generate {count} names with {seed}',
                'count': 4,
            })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['usernames'], ['acmesales', 'john', 'bad'])
        self.assertIn('/chat/completions', post_mock.call_args.args[0])

        prose_payload = {
            'choices': [{
                'message': {
                    'content': 'Sure, here are 3 usernames:\n1. alpha.sales\n2. beta_ops\n3. carol@example.com'
                }
            }]
        }
        with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(payload=prose_payload)):
            prose_response = self.client.post('/api/cloudflare/ai-usernames/test', json={
                'api_url': 'https://ai.example.com/v1',
                'model': 'gpt-test',
                'api_key': 'secret-key',
                'prompt': 'Generate {count} names with {seed}',
                'count': 3,
            })
        prose_result = prose_response.get_json()
        self.assertTrue(prose_result['success'], prose_result)
        self.assertEqual(prose_result['usernames'], ['alphasales', 'betaops', 'carol'])
        self.assertNotIn('surehereare3usernames', prose_result['usernames'])

        unsupported_payload = {'message': 'Sure, here are usernames: alpha, beta'}
        with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(payload=unsupported_payload)):
            unsupported_response = self.client.post('/api/cloudflare/ai-usernames/test', json={
                'api_url': 'https://ai.example.com/v1',
                'model': 'gpt-test',
                'api_key': 'secret-key',
                'prompt': 'Generate {count}',
                'count': 2,
            })
        unsupported_result = unsupported_response.get_json()
        self.assertFalse(unsupported_result['success'])
        self.assertIn('缺少用户名列表', unsupported_result['error'])

        missing_response = self.client.post('/api/cloudflare/ai-usernames/test', json={
            'api_url': '',
            'model': 'gpt-test',
            'api_key': 'secret-key',
            'prompt': 'Generate {count}',
        })
        missing_payload = missing_response.get_json()
        self.assertFalse(missing_payload['success'])
        self.assertIn('API 地址', missing_payload['error'])

        with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(status_code=500, text='bad gateway')):
            failed_response = self.client.post('/api/cloudflare/ai-usernames/test', json={
                'api_url': 'https://ai.example.com/v1',
                'model': 'gpt-test',
                'api_key': 'secret-key',
                'prompt': 'Generate {count}',
                'count': 2,
            })
        failed_payload = failed_response.get_json()
        self.assertFalse(failed_payload['success'])
        self.assertIn('AI', failed_payload['error'])

    def test_ai_username_generate_endpoint_uses_saved_enabled_config_with_exact_count(self):
        self.enable_saved_ai_username_config()
        success_payload = {
            'choices': [{
                'message': {
                    'content': '["Alpha.One", "Beta_Two", "carol@example.com"]'
                }
            }]
        }

        with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(payload=success_payload)) as post_mock:
            response = self.client.post('/api/cloudflare/ai-usernames/generate', json={'count': 3})

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)
        self.assertEqual(payload['usernames'], ['alphaone', 'betatwo', 'carol'])
        self.assertIn('/chat/completions', post_mock.call_args.args[0])

        with self.app.app_context():
            db = web_outlook_app.get_db()
            count = db.execute('SELECT COUNT(*) AS count FROM temp_emails').fetchone()['count']
            self.assertEqual(count, 0)

    def test_ai_username_generate_endpoint_requires_saved_enabled_config(self):
        disabled_response = self.client.post('/api/cloudflare/ai-usernames/generate', json={'count': 2})
        disabled_payload = disabled_response.get_json()
        self.assertFalse(disabled_payload['success'])
        self.assertIn('未启用', disabled_payload['error'])

        with self.app.app_context():
            web_outlook_app.set_setting('cloudflare_ai_username_enabled', 'true')
            web_outlook_app.set_setting('cloudflare_ai_username_api_url', '')
            web_outlook_app.set_setting('cloudflare_ai_username_model', 'gpt-test')
            web_outlook_app.set_setting('cloudflare_ai_username_api_key', web_outlook_app.encrypt_data('secret-key'))

        missing_response = self.client.post('/api/cloudflare/ai-usernames/generate', json={'count': 2})
        missing_payload = missing_response.get_json()
        self.assertFalse(missing_payload['success'])
        self.assertIn('缺少', missing_payload['error'])

    def test_ai_username_generate_endpoint_rejects_count_mismatch_without_padding_or_truncating(self):
        self.enable_saved_ai_username_config()
        cases = [
            ('["alpha"]', '数量'),
            ('["alpha", "beta", "gamma"]', '数量'),
            ('["alpha", "alpha"]', '清洗后'),
        ]

        for content, expected_error in cases:
            with self.subTest(content=content):
                payload = {'choices': [{'message': {'content': content}}]}
                with patch.object(web_outlook_app.requests, 'post', return_value=FakeOpenAIResponse(payload=payload)), \
                        patch.object(web_outlook_app, 'generate_random_temp_name') as random_mock, \
                        patch.object(web_outlook_app, 'cloudflare_create_address') as create_mock:
                    response = self.client.post('/api/cloudflare/ai-usernames/generate', json={'count': 2})

                result = response.get_json()
                self.assertFalse(result['success'], result)
                self.assertIn(expected_error, result['error'])
                self.assertNotEqual(result.get('usernames'), ['alpha', 'beta'])
                random_mock.assert_not_called()
                create_mock.assert_not_called()


class CloudflareChannelImportExportTests(CloudflareChannelTestCase):
    def test_import_supports_channel_sections_and_legacy_default(self):
        us_channel_id = self.create_channel(name='cfmail-us', enabled=True, is_default=True)
        hk_channel_id = self.create_channel(name='cfmail-hk', enabled=True)

        response = self.client.post('/api/temp-emails/import', json={
            'provider': 'cloudflare',
            'account_string': '\n'.join([
                '[cloudflare:cfmail-hk]',
                'hk@hk.example.com----hk-jwt',
                '[cloudflare]',
                'legacy@us.example.com----legacy-jwt',
                'line@hk.example.com----line-jwt----cfmail-hk',
            ]),
        })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)

        with self.app.app_context():
            hk_email = web_outlook_app.get_temp_email_by_address('hk@hk.example.com')
            legacy_email = web_outlook_app.get_temp_email_by_address('legacy@us.example.com')
            line_email = web_outlook_app.get_temp_email_by_address('line@hk.example.com')
            self.assertEqual(hk_email['cloudflare_channel_id'], hk_channel_id)
            self.assertEqual(legacy_email['cloudflare_channel_id'], us_channel_id)
            self.assertEqual(line_email['cloudflare_channel_id'], hk_channel_id)

        response = self.client.post('/api/temp-emails/import', json={
            'provider': 'cloudflare',
            'account_string': '[cloudflare:missing]\nmissing@example.com----jwt',
        })
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('渠道不存在', payload['error'])

    def test_import_binds_tags_to_added_and_updated_cloudflare_emails(self):
        channel_id = self.create_channel(name='cfmail-tags', enabled=True, is_default=True)
        tag_id = self.create_tag(name='导入标签')

        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_temp_email(
                'existing@cfmail-tags.example.com',
                provider='cloudflare',
                cloudflare_jwt='old-jwt',
                cloudflare_channel_id=channel_id,
            ))

        response = self.client.post('/api/temp-emails/import', json={
            'provider': 'cloudflare',
            'tag_ids': [tag_id, 999999, 'bad'],
            'account_string': '\n'.join([
                'new@cfmail-tags.example.com----new-jwt',
                'existing@cfmail-tags.example.com----updated-jwt',
            ]),
        })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)

        with self.app.app_context():
            new_email = web_outlook_app.get_temp_email_by_address('new@cfmail-tags.example.com')
            existing_email = web_outlook_app.get_temp_email_by_address('existing@cfmail-tags.example.com')
            self.assertEqual(
                [tag['id'] for tag in web_outlook_app.get_temp_email_tags(new_email['id'])],
                [tag_id],
            )
            self.assertEqual(
                [tag['id'] for tag in web_outlook_app.get_temp_email_tags(existing_email['id'])],
                [tag_id],
            )
            self.assertEqual(web_outlook_app.decrypt_data(existing_email['cloudflare_jwt']), 'updated-jwt')

    def test_export_groups_cloudflare_temp_emails_by_channel_name(self):
        us_channel_id = self.create_channel(name='cfmail-us', enabled=True, is_default=True)
        hk_channel_id = self.create_channel(name='cfmail-hk', enabled=True)

        with self.app.app_context():
            self.assertTrue(web_outlook_app.add_temp_email(
                'us@us.example.com',
                provider='cloudflare',
                cloudflare_jwt='us-jwt',
                cloudflare_channel_id=us_channel_id,
            ))
            self.assertTrue(web_outlook_app.add_temp_email(
                'hk@hk.example.com',
                provider='cloudflare',
                cloudflare_jwt='hk-jwt',
                cloudflare_channel_id=hk_channel_id,
            ))

            temp_group_id = web_outlook_app.get_temp_email_group_id()
            export_result = web_outlook_app.build_group_export_content([temp_group_id])

        content = '\n'.join(export_result['lines'])
        self.assertIn('[cloudflare:cfmail-us]', content)
        self.assertIn('us@us.example.com----us-jwt', content)
        self.assertIn('[cloudflare:cfmail-hk]', content)
        self.assertIn('hk@hk.example.com----hk-jwt', content)
