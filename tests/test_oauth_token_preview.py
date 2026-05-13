import pathlib


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
OAUTH_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '06-utils-oauth.js'
OAUTH_DIALOG_PATH = ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-oauth.html'


def test_exchange_token_preview_only_requires_redirect_url_before_request():
    source = OAUTH_JS_PATH.read_text(encoding='utf-8')
    exchange_start = source.index('async function exchangeToken')
    request_start = source.index("fetch('/api/oauth/exchange-token'", exchange_start)
    pre_request_logic = source[exchange_start:request_start]

    assert "if (!redirectUrl)" in pre_request_logic
    assert "if (!groupId)" not in pre_request_logic
    assert "if (!email || !password)" not in pre_request_logic
    assert "请先输入邮箱账号和密码" not in pre_request_logic


def test_oauth_preview_labels_account_fields_optional():
    html = OAUTH_DIALOG_PATH.read_text(encoding='utf-8')

    assert '邮箱账号（保存时可选）' in html
    assert '密码（保存时可选）' in html
    assert '换取并预览只需要粘贴授权后的回调 URL' in html
