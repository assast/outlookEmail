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


def test_reauthorize_mode_posts_to_account_endpoint_without_saving_new_account():
    source = OAUTH_JS_PATH.read_text(encoding='utf-8')
    save_start = source.index('async function saveTokenAccount')
    new_account_post = source.index("fetch('/api/accounts'", save_start)
    save_pre_new_account = source[save_start:new_account_post]

    assert 'if (isOAuthReauthorizeMode())' in save_pre_new_account
    assert 'return reauthorizeExistingAccount();' in save_pre_new_account
    assert 'fetch(`/api/accounts/${accountId}/reauthorize`' in source


def test_reauthorize_entry_is_scoped_to_outlook_accounts():
    oauth_html = OAUTH_DIALOG_PATH.read_text(encoding='utf-8')
    groups_js = (ROOT_DIR / 'static' / 'js' / 'index' / '02-groups.js').read_text(encoding='utf-8')
    primary_html = (ROOT_DIR / 'templates' / 'partials' / 'index' / 'dialogs-primary.html').read_text(encoding='utf-8')

    assert 'id="editReauthorizeGroup"' in primary_html
    assert '重新授权并刷新' in primary_html
    assert "reauthorizeGroup.style.display = isOutlook ? '' : 'none'" in groups_js
    assert 'id="oauthPasswordGroup"' in oauth_html
    assert 'id="oauthTargetGroup"' in oauth_html
    assert 'id="oauthForwardGroup"' in oauth_html
