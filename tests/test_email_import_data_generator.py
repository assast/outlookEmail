import unittest
from dataclasses import dataclass


@dataclass(frozen=True)
class EmailImportDataGenerator:
    count: int = 10100
    email_prefix: str = 'import'
    domain: str = 'example.com'
    password_prefix: str = 'imap-password'

    def lines(self):
        return [
            f'{self.email_prefix}{index:05d}@{self.domain}----{self.password_prefix}-{index}'
            for index in range(self.count)
        ]

    def account_string(self):
        return '\n'.join(self.lines())

    def api_payload(self, group_id: int = 1, provider: str = 'gmail'):
        return {
            'account_string': self.account_string(),
            'group_id': group_id,
            'provider': provider,
        }


class EmailImportDataGeneratorTests(unittest.TestCase):
    def test_generates_10100_email_import_lines(self):
        generator = EmailImportDataGenerator()

        lines = generator.lines()

        self.assertEqual(len(lines), 10100)
        self.assertEqual(len(set(lines)), 10100)
        self.assertEqual(lines[0], 'import00000@example.com----imap-password-0')
        self.assertEqual(lines[-1], 'import10099@example.com----imap-password-10099')

    def test_generates_accounts_api_payload(self):
        generator = EmailImportDataGenerator()

        payload = generator.api_payload(group_id=7, provider='gmail')

        self.assertEqual(payload['group_id'], 7)
        self.assertEqual(payload['provider'], 'gmail')
        self.assertEqual(len(payload['account_string'].splitlines()), 10100)


if __name__ == '__main__':
    unittest.main()
