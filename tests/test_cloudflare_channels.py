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
            db.execute('DELETE FROM temp_email_tags')
            db.execute('DELETE FROM temp_email_messages')
            db.execute('DELETE FROM temp_emails')
            db.execute('DELETE FROM cloudflare_channels')
            db.execute("UPDATE settings SET value = '' WHERE key IN ('cloudflare_worker_domain', 'cloudflare_email_domains', 'cloudflare_admin_password')")
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
            ]),
        })

        payload = response.get_json()
        self.assertTrue(payload['success'], payload)

        with self.app.app_context():
            hk_email = web_outlook_app.get_temp_email_by_address('hk@hk.example.com')
            legacy_email = web_outlook_app.get_temp_email_by_address('legacy@us.example.com')
            self.assertEqual(hk_email['cloudflare_channel_id'], hk_channel_id)
            self.assertEqual(legacy_email['cloudflare_channel_id'], us_channel_id)

        response = self.client.post('/api/temp-emails/import', json={
            'provider': 'cloudflare',
            'account_string': '[cloudflare:missing]\nmissing@example.com----jwt',
        })
        payload = response.get_json()
        self.assertFalse(payload['success'])
        self.assertIn('渠道不存在', payload['error'])

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
