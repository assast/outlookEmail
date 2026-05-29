import ast
import importlib
import inspect
import os
import pathlib
import sys
import tempfile


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-imap-helper-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

HELPERS_PATH = ROOT_DIR / 'outlook_web' / 'segments' / '03_mail_helpers.py'
EXPECTED_PARAMETERS = [
    'account',
    'client_id',
    'refresh_token',
    'folder',
    'skip',
    'top',
    'server',
    'proxy_url',
    'fallback_proxy_urls',
]


def _imap_server_helper_defs():
    tree = ast.parse(HELPERS_PATH.read_text(encoding='utf-8'))
    return [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'get_emails_imap_with_server'
    ]


def test_get_emails_imap_with_server_has_one_real_definition():
    definitions = _imap_server_helper_defs()

    assert len(definitions) == 1
    assert [arg.arg for arg in definitions[0].args.args] == EXPECTED_PARAMETERS


def test_get_emails_imap_with_server_import_signature_matches_routes():
    web_outlook_app = importlib.import_module('web_outlook_app')

    helper = web_outlook_app.get_emails_imap_with_server
    signature = inspect.signature(helper)

    assert callable(helper)
    assert list(signature.parameters) == EXPECTED_PARAMETERS
    assert signature.parameters['fallback_proxy_urls'].default is None
