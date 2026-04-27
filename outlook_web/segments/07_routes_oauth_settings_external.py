from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # These segmented files are executed into the shared `web_outlook_app`
    # globals at runtime. Importing from the assembled module keeps IDE
    # inspections from flagging the shared names as unresolved.
    from web_outlook_app import *  # noqa: F403


# ==================== OAuth Token API ====================

@app.route('/api/oauth/auth-url', methods=['GET'])
@login_required
def api_get_oauth_auth_url():
    """生成 OAuth 授权 URL"""
    import urllib.parse

    base_auth_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    params = {
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(OAUTH_SCOPES),
        "state": "12345"
    }
    auth_url = f"{base_auth_url}?{urllib.parse.urlencode(params)}"

    return jsonify({
        'success': True,
        'auth_url': auth_url,
        'client_id': OAUTH_CLIENT_ID,
        'redirect_uri': OAUTH_REDIRECT_URI
    })


@app.route('/api/oauth/exchange-token', methods=['POST'])
@login_required
def api_exchange_oauth_token():
    """使用授权码换取 Refresh Token"""
    import urllib.parse

    data = request.json
    redirected_url = data.get('redirected_url', '').strip()

    if not redirected_url:
        return jsonify({'success': False, 'error': '请提供授权后的完整 URL'})

    # 从 URL 中提取 code
    try:
        parsed_url = urllib.parse.urlparse(redirected_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        auth_code = query_params['code'][0]
    except (KeyError, IndexError):
        return jsonify({'success': False, 'error': '无法从 URL 中提取授权码，请检查 URL 是否正确'})

    # 使用 Code 换取 Token (Public Client 不需要 client_secret)
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    token_data = {
        "client_id": OAUTH_CLIENT_ID,
        "code": auth_code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": " ".join(OAUTH_SCOPES)
    }

    try:
        response = requests.post(token_url, data=token_data, timeout=30)
    except Exception as e:
        return jsonify({'success': False, 'error': f'请求失败: {str(e)}'})

    if response.status_code == 200:
        tokens = response.json()
        refresh_token = tokens.get('refresh_token')

        if not refresh_token:
            return jsonify({'success': False, 'error': '未能获取 Refresh Token'})

        return jsonify({
            'success': True,
            'refresh_token': refresh_token,
            'client_id': OAUTH_CLIENT_ID,
            'token_type': tokens.get('token_type'),
            'expires_in': tokens.get('expires_in'),
            'scope': tokens.get('scope')
        })
    else:
        error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        error_msg = error_data.get('error_description', response.text)
        return jsonify({'success': False, 'error': f'获取令牌失败: {error_msg}'})


# ==================== 设置 API ====================

@app.route('/api/settings/validate-cron', methods=['POST'])
@login_required
def api_validate_cron():
    """验证 Cron 表达式"""
    try:
        from croniter import croniter
        from datetime import datetime
    except ImportError:
        return jsonify({'success': False, 'error': 'croniter 库未安装，请运行: pip install croniter'})

    data = request.json or {}
    cron_expr = data.get('cron_expression', '').strip()
    requested_timezone = str(data.get('time_zone', '')).strip()

    if not cron_expr:
        return jsonify({'success': False, 'error': 'Cron 表达式不能为空'})

    if requested_timezone and not is_valid_app_timezone_name(requested_timezone):
        return jsonify({'success': False, 'error': 'Invalid time zone'})

    preview_timezone = normalize_app_timezone_name(requested_timezone, get_app_timezone())
    tzinfo = ZoneInfo(preview_timezone)

    try:
        base_time = datetime.now(tzinfo)
        cron = croniter(cron_expr, base_time)

        next_run = cron.get_next(datetime)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=tzinfo)

        future_runs = []
        temp_cron = croniter(cron_expr, base_time)
        for _ in range(5):
            future_run = temp_cron.get_next(datetime)
            if future_run.tzinfo is None:
                future_run = future_run.replace(tzinfo=tzinfo)
            future_runs.append(future_run.isoformat())

        return jsonify({
            'success': True,
            'valid': True,
            'next_run': next_run.isoformat(),
            'future_runs': future_runs,
            'time_zone': preview_timezone
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'valid': False,
            'error': f'Cron 表达式无效: {str(e)}'
        })


@app.route('/api/settings', methods=['GET'])
@login_required
def api_get_settings():
    """获取所有设置"""
    settings = get_all_settings()
    # 隐藏密码的部分字符
    if 'login_password' in settings:
        pwd = settings['login_password']
        if len(pwd) > 2:
            settings['login_password_masked'] = pwd[0] + '*' * (len(pwd) - 2) + pwd[-1]
        else:
            settings['login_password_masked'] = '*' * len(pwd)
    # 返回解密后的对外 API Key
    settings['external_api_key'] = get_external_api_key()
    # 返回 DuckMail 设置
    settings['duckmail_base_url'] = get_duckmail_base_url()
    settings['duckmail_api_key'] = get_duckmail_api_key()
    settings['cloudflare_worker_domain'] = get_cloudflare_worker_domain()
    settings['cloudflare_email_domains'] = ', '.join(get_cloudflare_email_domains())
    settings['cloudflare_admin_password'] = get_cloudflare_admin_password()
    settings['app_timezone'] = get_app_timezone()
    settings['show_account_created_at'] = get_setting('show_account_created_at', 'true')
    settings['forward_channels'] = get_forward_channels()
    settings['forward_check_interval_minutes'] = get_setting('forward_check_interval_minutes', '5')
    settings['forward_email_window_minutes'] = get_setting('forward_email_window_minutes', '0')
    settings['forward_include_junkemail'] = get_setting('forward_include_junkemail', 'false')
    settings['email_forward_recipient'] = get_setting('email_forward_recipient', '')
    settings['smtp_host'] = get_setting('smtp_host', '')
    settings['smtp_port'] = get_setting('smtp_port', '465')
    settings['smtp_username'] = get_setting('smtp_username', '')
    settings['smtp_password'] = get_setting_decrypted('smtp_password', '')
    settings['smtp_from_email'] = get_setting('smtp_from_email', '')
    settings['smtp_provider'] = normalize_smtp_forward_provider(get_setting('smtp_provider', 'custom'))
    settings['smtp_use_tls'] = get_setting('smtp_use_tls', 'false')
    settings['smtp_use_ssl'] = get_setting('smtp_use_ssl', 'true')
    settings['telegram_bot_token'] = get_setting_decrypted('telegram_bot_token', '')
    settings['telegram_chat_id'] = get_setting('telegram_chat_id', '')
    settings['telegram_proxy_url'] = get_setting('telegram_proxy_url', '')
    settings['wecom_webhook_url'] = get_setting_decrypted('wecom_webhook_url', '')
    return jsonify({'success': True, 'settings': settings})


@app.route('/api/settings', methods=['PUT'])
@login_required
def api_update_settings():
    """更新设置"""
    data = request.json or {}
    updated = []
    errors = []

    # 更新登录密码
    if 'login_password' in data:
        new_password = data['login_password'].strip()
        if new_password:
            if len(new_password) < 8:
                errors.append('密码长度至少为 8 位')
            else:
                # 哈希新密码
                hashed_password = hash_password(new_password)
                if set_setting('login_password', hashed_password):
                    updated.append('登录密码')
                else:
                    errors.append('更新登录密码失败')

    # 更新 GPTMail API Key
    if 'gptmail_api_key' in data:
        new_api_key = data['gptmail_api_key'].strip()
        if new_api_key:
            if set_setting('gptmail_api_key', new_api_key):
                updated.append('GPTMail API Key')
            else:
                errors.append('更新 GPTMail API Key 失败')

    # 更新刷新周期
    if 'refresh_interval_days' in data:
        try:
            days = int(data['refresh_interval_days'])
            if days < 1 or days > 90:
                errors.append('刷新周期必须在 1-90 天之间')
            elif set_setting('refresh_interval_days', str(days)):
                updated.append('刷新周期')
            else:
                errors.append('更新刷新周期失败')
        except ValueError:
            errors.append('刷新周期必须是数字')

    # 更新刷新间隔
    if 'refresh_delay_seconds' in data:
        try:
            seconds = int(data['refresh_delay_seconds'])
            if seconds < 0 or seconds > 60:
                errors.append('刷新间隔必须在 0-60 秒之间')
            elif set_setting('refresh_delay_seconds', str(seconds)):
                updated.append('刷新间隔')
            else:
                errors.append('更新刷新间隔失败')
        except ValueError:
            errors.append('刷新间隔必须是数字')

    # 更新 Cron 表达式
    if 'refresh_cron' in data:
        cron_expr = data['refresh_cron'].strip()
        if cron_expr:
            try:
                from croniter import croniter
                from datetime import datetime
                croniter(cron_expr, datetime.now())
                if set_setting('refresh_cron', cron_expr):
                    updated.append('Cron 表达式')
                else:
                    errors.append('更新 Cron 表达式失败')
            except ImportError:
                errors.append('croniter 库未安装')
            except Exception as e:
                errors.append(f'Cron 表达式无效: {str(e)}')

    # 更新刷新策略
    if 'use_cron_schedule' in data:
        use_cron = str(data['use_cron_schedule']).lower()
        if use_cron in ('true', 'false'):
            if set_setting('use_cron_schedule', use_cron):
                updated.append('刷新策略')
            else:
                errors.append('更新刷新策略失败')
        else:
            errors.append('刷新策略必须是 true 或 false')

    # 更新定时刷新开关
    if 'enable_scheduled_refresh' in data:
        enable = str(data['enable_scheduled_refresh']).lower()
        if enable in ('true', 'false'):
            if set_setting('enable_scheduled_refresh', enable):
                updated.append('定时刷新开关')
            else:
                errors.append('更新定时刷新开关失败')
        else:
            errors.append('定时刷新开关必须是 true 或 false')

    if 'app_timezone' in data:
        app_timezone = str(data['app_timezone']).strip()
        if not is_valid_app_timezone_name(app_timezone):
            errors.append('Invalid time zone')
        elif set_setting('app_timezone', app_timezone):
            updated.append('Time zone')
        else:
            errors.append('Failed to save time zone')

    if 'show_account_created_at' in data:
        show_created_at = str(data['show_account_created_at']).lower()
        if show_created_at in ('true', 'false'):
            if set_setting('show_account_created_at', show_created_at):
                updated.append('创建时间展示')
            else:
                errors.append('更新创建时间展示失败')
        else:
            errors.append('创建时间展示必须是 true 或 false')

    # 更新对外 API Key
    if 'external_api_key' in data:
        new_ext_key = data['external_api_key'].strip()
        if new_ext_key:
            if set_setting('external_api_key', new_ext_key):
                updated.append('对外 API Key')
            else:
                errors.append('更新对外 API Key 失败')
        else:
            if set_setting('external_api_key', ''):
                updated.append('对外 API Key（已清空）')

    # 更新 DuckMail 设置
    if 'duckmail_base_url' in data:
        new_url = data['duckmail_base_url'].strip()
        if set_setting('duckmail_base_url', new_url):
            updated.append('DuckMail API 地址')
        else:
            errors.append('更新 DuckMail API 地址失败')

    if 'duckmail_api_key' in data:
        new_dk_key = data['duckmail_api_key'].strip()
        if set_setting('duckmail_api_key', new_dk_key):
            updated.append('DuckMail API Key')
        else:
            errors.append('更新 DuckMail API Key 失败')

    if 'cloudflare_worker_domain' in data:
        new_domain = data['cloudflare_worker_domain'].strip()
        if set_setting('cloudflare_worker_domain', new_domain):
            updated.append('Cloudflare Worker 域名')
        else:
            errors.append('更新 Cloudflare Worker 域名失败')

    if 'cloudflare_email_domains' in data:
        new_domains = data['cloudflare_email_domains'].strip()
        if set_setting('cloudflare_email_domains', new_domains):
            updated.append('Cloudflare 邮箱域名')
        else:
            errors.append('更新 Cloudflare 邮箱域名失败')

    if 'cloudflare_admin_password' in data:
        new_password = data['cloudflare_admin_password'].strip()
        if set_setting('cloudflare_admin_password', new_password):
            updated.append('Cloudflare 管理密码')
        else:
            errors.append('更新 Cloudflare 管理密码失败')

    if 'forward_check_interval_minutes' in data:
        try:
            minutes = int(data['forward_check_interval_minutes'])
            if minutes < 1 or minutes > 60:
                errors.append('转发检查间隔必须在 1-60 分钟之间')
            elif set_setting('forward_check_interval_minutes', str(minutes)):
                updated.append('转发检查间隔')
            else:
                errors.append('保存转发检查间隔失败')
        except ValueError:
            errors.append('转发检查间隔必须是数字')

    if 'forward_email_window_minutes' in data:
        try:
            minutes = int(data['forward_email_window_minutes'])
            if minutes < 0 or minutes > 10080:
                errors.append('转发邮件时间范围必须在 0-10080 分钟之间')
            elif set_setting('forward_email_window_minutes', str(minutes)):
                updated.append('转发邮件时间范围')
            else:
                errors.append('保存转发邮件时间范围失败')
        except ValueError:
            errors.append('转发邮件时间范围必须是数字')

    if 'forward_include_junkemail' in data:
        include_junk = str(data['forward_include_junkemail']).lower()
        if include_junk in ('true', 'false'):
            if set_setting('forward_include_junkemail', include_junk):
                updated.append('转发垃圾箱邮件')
            else:
                errors.append('保存转发垃圾箱邮件失败')
        else:
            errors.append('转发垃圾箱邮件必须是 true 或 false')

    if 'forward_channels' in data:
        forward_channels = normalize_forward_channel_settings(data['forward_channels'])
        stored_value = ','.join(forward_channels) if forward_channels else 'none'
        if set_setting('forward_channels', stored_value):
            updated.append('转发渠道')
        else:
            errors.append('保存转发渠道失败')

    if 'email_forward_recipient' in data:
        if set_setting('email_forward_recipient', data['email_forward_recipient'].strip()):
            updated.append('邮件转发收件箱')
        else:
            errors.append('保存邮件转发收件箱失败')

    if 'smtp_host' in data:
        if set_setting('smtp_host', data['smtp_host'].strip()):
            updated.append('SMTP 主机')
        else:
            errors.append('保存 SMTP 主机失败')

    if 'smtp_port' in data:
        try:
            smtp_port = int(data['smtp_port'])
            if smtp_port <= 0 or smtp_port > 65535:
                errors.append('SMTP 端口无效')
            elif set_setting('smtp_port', str(smtp_port)):
                updated.append('SMTP 端口')
            else:
                errors.append('保存 SMTP 端口失败')
        except ValueError:
            errors.append('SMTP 端口必须是数字')

    if 'smtp_username' in data:
        if set_setting('smtp_username', data['smtp_username'].strip()):
            updated.append('SMTP 用户名')
        else:
            errors.append('保存 SMTP 用户名失败')

    if 'smtp_password' in data:
        if set_setting_encrypted('smtp_password', data['smtp_password'].strip()):
            updated.append('SMTP 密码')
        else:
            errors.append('保存 SMTP 密码失败')

    if 'smtp_from_email' in data:
        if set_setting('smtp_from_email', data['smtp_from_email'].strip()):
            updated.append('SMTP 发件人')
        else:
            errors.append('保存 SMTP 发件人失败')

    if 'smtp_provider' in data:
        smtp_provider = normalize_smtp_forward_provider(data['smtp_provider'])
        if str(data['smtp_provider']).strip().lower() not in SMTP_FORWARD_PROVIDERS:
            errors.append('SMTP 邮箱类型无效')
        elif set_setting('smtp_provider', smtp_provider):
            updated.append('SMTP 邮箱类型')
        else:
            errors.append('保存 SMTP 邮箱类型失败')

    if 'smtp_use_tls' in data:
        if set_setting('smtp_use_tls', str(data['smtp_use_tls']).lower()):
            updated.append('SMTP TLS')
        else:
            errors.append('保存 SMTP TLS 失败')

    if 'smtp_use_ssl' in data:
        if set_setting('smtp_use_ssl', str(data['smtp_use_ssl']).lower()):
            updated.append('SMTP SSL')
        else:
            errors.append('保存 SMTP SSL 失败')

    if 'telegram_bot_token' in data:
        if set_setting_encrypted('telegram_bot_token', data['telegram_bot_token'].strip()):
            updated.append('Telegram Bot Token')
        else:
            errors.append('保存 Telegram Bot Token 失败')

    if 'telegram_chat_id' in data:
        if set_setting('telegram_chat_id', data['telegram_chat_id'].strip()):
            updated.append('Telegram Chat ID')
        else:
            errors.append('保存 Telegram Chat ID 失败')

    if 'telegram_proxy_url' in data:
        if set_setting('telegram_proxy_url', data['telegram_proxy_url'].strip()):
            updated.append('Telegram 代理')
        else:
            errors.append('保存 Telegram 代理失败')

    if 'wecom_webhook_url' in data:
        if set_setting_encrypted('wecom_webhook_url', data['wecom_webhook_url'].strip()):
            updated.append('企业微信 Webhook')
        else:
            errors.append('保存企业微信 Webhook 失败')

    if errors:
        return jsonify({'success': False, 'error': '；'.join(errors)})

    if updated:
        return jsonify({'success': True, 'message': f'已更新：{", ".join(updated)}'})
    else:
        return jsonify({'success': False, 'error': '没有需要更新的设置'})


# ==================== 对外 API ====================

@app.route('/api/external/emails', methods=['GET'])
@csrf_exempt
@api_key_required
def api_external_get_emails():
    """对外 API：通过 API Key 获取邮件列表"""
    email_addr = get_query_arg_preserve_plus('email', '').strip()
    folder = request.args.get('folder', 'inbox').strip().lower()
    skip = int(request.args.get('skip', 0))
    top = int(request.args.get('top', 20))

    if not email_addr:
        return jsonify({'success': False, 'error': '缺少 email 参数'}), 400

    # 验证 folder 参数
    valid_folders = ['inbox', 'junkemail']
    if folder not in valid_folders:
        return jsonify({'success': False, 'error': f'folder 参数无效，支持: {", ".join(valid_folders)}'}), 400

    # 限制分页大小
    if top > 50:
        top = 50

    account = resolve_account_for_email_api(email_addr)
    if not account:
        return jsonify({'success': False, 'error': '邮箱账号不存在'}), 404

    # 获取分组代理设置
    proxy_url = get_account_proxy_url(account)
    fallback_proxy_urls = get_account_proxy_failover_urls(account)

    # 收集所有错误信息
    all_errors = {}

    # 1. 尝试 Graph API
    graph_result = get_emails_graph(
        account['client_id'],
        account['refresh_token'],
        folder,
        skip,
        top,
        proxy_url,
        fallback_proxy_urls,
    )
    if graph_result.get('success'):
        emails = graph_result.get('emails', [])
        formatted = [format_graph_email_item(e, folder) for e in emails]
        return jsonify({
            'success': True,
            'emails': formatted,
            'method': 'Graph API',
            'has_more': len(formatted) >= top
        })
    else:
        graph_error = graph_result.get('error')
        all_errors['graph'] = graph_error
        if isinstance(graph_error, dict) and graph_error.get('type') in ('ProxyError', 'ConnectionError'):
            return jsonify({'success': False, 'error': '代理连接失败', 'details': all_errors})

    # 2. 尝试新版 IMAP
    imap_new_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_NEW, proxy_url, fallback_proxy_urls
    )
    if imap_new_result.get('success'):
        return jsonify({
            'success': True,
            'emails': imap_new_result.get('emails', []),
            'method': 'IMAP (New)',
            'has_more': False
        })
    else:
        all_errors['imap_new'] = imap_new_result.get('error')

    # 3. 尝试旧版 IMAP
    imap_old_result = get_emails_imap_with_server(
        account['email'], account['client_id'], account['refresh_token'],
        folder, skip, top, IMAP_SERVER_OLD, proxy_url, fallback_proxy_urls
    )
    if imap_old_result.get('success'):
        return jsonify({
            'success': True,
            'emails': imap_old_result.get('emails', []),
            'method': 'IMAP (Old)',
            'has_more': False
        })
    else:
        all_errors['imap_old'] = imap_old_result.get('error')

    return jsonify({'success': False, 'error': '无法获取邮件，所有方式均失败', 'details': all_errors})
