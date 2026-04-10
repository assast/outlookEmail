@app.route('/login', methods=['GET', 'POST'])
@csrf_exempt  # 登录接口排除CSRF保护（用户未登录时无法获取token）
def login():
    """登录页面"""
    if request.method == 'POST':
        try:
            # 获取客户端 IP
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(',')[0].strip()

            # 检查速率限制
            allowed, remaining_time = check_rate_limit(client_ip)
            if not allowed:
                return jsonify({
                    'success': False,
                    'error': f'登录失败次数过多，请在 {remaining_time} 秒后重试'
                }), 429

            data = request.json if request.is_json else request.form
            password = data.get('password', '')

            # 从数据库获取密码哈希
            stored_password = get_login_password()

            # 验证密码
            if verify_password(password, stored_password):
                # 登录成功，重置失败记录
                reset_login_attempts(client_ip)
                session['logged_in'] = True
                session.permanent = True
                session.modified = True  # 确保 Flask-Session 保存 session
                return jsonify({'success': True, 'message': '登录成功'})
            else:
                # 登录失败，记录失败次数
                record_login_failure(client_ip)
                return jsonify({'success': False, 'error': '密码错误'})
        except Exception as e:
            print(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'登录处理失败: {str(e)}'}), 500

    # GET 请求返回登录页面
    return render_template('login.html')


@app.route('/logout')
def logout():
    """退出登录"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/favicon.ico')
def favicon():
    """返回内联 SVG favicon，避免 500 错误"""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <rect width="100" height="100" rx="20" fill="#1a1a1a"/>
        <text x="50" y="55" font-size="60" text-anchor="middle" dominant-baseline="middle">📧</text>
    </svg>'''
    response = make_response(svg)
    response.headers['Content-Type'] = 'image/svg+xml'
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    return response


@app.route('/')
@login_required
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/csrf-token', methods=['GET'])
@csrf_exempt  # CSRF token获取接口排除CSRF保护
def get_csrf_token():
    """获取CSRF Token"""
    if CSRF_AVAILABLE:
        token = generate_csrf()
        return jsonify({'csrf_token': token})
    else:
        return jsonify({'csrf_token': None, 'csrf_disabled': True})


# ==================== 分组 API ====================

@app.route('/api/groups', methods=['GET'])
@login_required
def api_get_groups():
    """获取所有分组"""
    groups = load_groups()
    movable_position = 1
    # 添加每个分组的邮箱数量
    for group in groups:
        if group['name'] == '临时邮箱':
            # 临时邮箱分组从 temp_emails 表获取数量
            group['account_count'] = get_temp_email_count()
            group['sort_position'] = None
        else:
            group['account_count'] = get_group_account_count(group['id'])
            group['sort_position'] = movable_position
            movable_position += 1
    return jsonify({'success': True, 'groups': groups})


@app.route('/api/groups/<int:group_id>', methods=['GET'])
@login_required
def api_get_group(group_id):
    """获取单个分组"""
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})
    group['account_count'] = get_group_account_count(group_id)
    group['sort_position'] = get_group_sort_position(group_id)
    return jsonify({'success': True, 'group': group})


@app.route('/api/groups', methods=['POST'])
@login_required
def api_add_group():
    """添加分组"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=100)
    description = sanitize_input(data.get('description', ''), max_length=500)
    color = data.get('color', '#1a1a1a')
    proxy_url = data.get('proxy_url', '').strip()
    sort_position_raw = data.get('sort_position')

    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})

    try:
        sort_position = int(sort_position_raw) if sort_position_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '排序位置无效'})

    group_id = add_group(name, description, color, proxy_url, sort_position)
    if group_id:
        return jsonify({'success': True, 'message': '分组创建成功', 'group_id': group_id})
    else:
        return jsonify({'success': False, 'error': '分组名称已存在'})


@app.route('/api/groups/<int:group_id>', methods=['PUT'])
@login_required
def api_update_group(group_id):
    """更新分组"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=100)
    description = sanitize_input(data.get('description', ''), max_length=500)
    color = data.get('color', '#1a1a1a')
    proxy_url = data.get('proxy_url', '').strip()
    sort_position_raw = data.get('sort_position')

    if not name:
        return jsonify({'success': False, 'error': '分组名称不能为空'})

    try:
        sort_position = int(sort_position_raw) if sort_position_raw not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '排序位置无效'})

    if update_group(group_id, name, description, color, proxy_url, sort_position):
        return jsonify({'success': True, 'message': '分组更新成功'})
    else:
        return jsonify({'success': False, 'error': '更新失败'})


@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
@login_required
def api_delete_group(group_id):
    """删除分组"""
    if group_id == 1:
        return jsonify({'success': False, 'error': '默认分组不能删除'})
    
    if delete_group(group_id):
        return jsonify({'success': True, 'message': '分组已删除，邮箱已移至默认分组'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/groups/reorder', methods=['PUT'])
@login_required
def api_reorder_groups():
    """重新排序分组"""
    data = request.json or {}
    group_ids = data.get('group_ids', [])

    if not isinstance(group_ids, list) or not all(isinstance(group_id, int) for group_id in group_ids):
        return jsonify({'success': False, 'error': '分组排序参数无效'})

    if reorder_groups(group_ids):
        return jsonify({'success': True, 'message': '分组排序已更新'})
    else:
        return jsonify({'success': False, 'error': '分组排序失败'})


@app.route('/api/groups/<int:group_id>/export')
@login_required
def api_export_group(group_id):
    """导出分组下的所有邮箱账号为 TXT 文件（需要二次验证）"""
    # 检查二次验证token（使用内存存储）
    verify_token = request.args.get('verify_token')
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]

    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '分组不存在'})

    lines = []
    is_temp_group = group['name'] == '临时邮箱'

    if is_temp_group:
        # 临时邮箱分组从 temp_emails 表获取数据
        temp_emails = load_temp_emails()
        if not temp_emails:
            return jsonify({'success': False, 'error': '该分组下没有临时邮箱'})

        lines.append(group['name'])

        # 按渠道分组
        gptmail_list = [te for te in temp_emails if te.get('provider', 'gptmail') == 'gptmail']
        duckmail_list = [te for te in temp_emails if te.get('provider') == 'duckmail']
        cloudflare_list = [te for te in temp_emails if te.get('provider') == 'cloudflare']

        if gptmail_list:
            lines.append('[gptmail]')
            for te in gptmail_list:
                lines.append(te['email'])

        if duckmail_list:
            lines.append('[duckmail]')
            for te in duckmail_list:
                duckmail_password = decrypt_data(te.get('duckmail_password', '')) if te.get('duckmail_password') else ''
                lines.append(f"{te['email']}----{duckmail_password}")

        if cloudflare_list:
            lines.append('[cloudflare]')
            for te in cloudflare_list:
                cloudflare_jwt = decrypt_data(te.get('cloudflare_jwt', '')) if te.get('cloudflare_jwt') else ''
                lines.append(f"{te['email']}----{cloudflare_jwt}")

        log_audit('export', 'group', str(group_id), f"导出临时邮箱分组的 {len(temp_emails)} 个临时邮箱")
    else:
        # 普通分组从 accounts 表获取数据
        accounts = load_accounts(group_id)
        if not accounts:
            return jsonify({'success': False, 'error': '该分组下没有邮箱账号'})

        lines.append(group['name'])
        log_audit('export', 'group', str(group_id), f"导出分组 '{group['name']}' 的 {len(accounts)} 个账号")

        for acc in accounts:
            line = format_account_export_line(acc)
            lines.append(line)

    content = '\n'.join(lines)

    # 生成文件名（使用 URL 编码处理中文）
    filename = f"{group['name']}_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )

def format_account_export_line(account: Dict[str, Any]) -> str:
    if account.get('account_type') == 'imap':
        provider = account.get('provider', 'custom')
        imap_password = account.get('imap_password', '')
        if provider == 'custom':
            return f"{account['email']}----{imap_password}----{account.get('imap_host', '')}----{account.get('imap_port', 993)}"
        return f"{account['email']}----{imap_password}"
    return f"{account['email']}----{account.get('password', '')}----{account.get('client_id', '')}----{account.get('refresh_token', '')}"


@app.route('/api/accounts/export')
@login_required
def api_export_all_accounts():
    """导出所有邮箱账号为 TXT 文件（需要二次验证）"""
    # 检查二次验证token（使用内存存储）
    verify_token = request.args.get('verify_token')
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]


    # 使用 load_accounts 获取所有账号（自动解密）
    accounts = load_accounts()

    if not accounts:
        return jsonify({'success': False, 'error': '没有邮箱账号'})

    # 记录审计日志
    log_audit('export', 'all_accounts', None, f"导出所有账号，共 {len(accounts)} 个")

    # 生成导出内容（格式：email----password----client_id----refresh_token）
    lines = []
    for acc in accounts:
        line = format_account_export_line(acc)
        lines.append(line)

    content = '\n'.join(lines)

    # 生成文件名（使用 URL 编码处理中文）
    filename = f"all_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.route('/api/accounts/export-selected', methods=['POST'])
@login_required
def api_export_selected_accounts():
    """导出选中分组的邮箱账号为 TXT 文件（需要二次验证）"""
    data = request.json
    group_ids = data.get('group_ids', [])
    verify_token = data.get('verify_token')

    # 检查二次验证token（使用内存存储）
    import time
    if not verify_token or verify_token not in export_verify_tokens:
        return jsonify({'success': False, 'error': '需要二次验证', 'need_verify': True}), 401
    
    token_data = export_verify_tokens[verify_token]
    
    # 检查是否过期
    if token_data['expires'] < time.time():
        del export_verify_tokens[verify_token]
        return jsonify({'success': False, 'error': '验证已过期，请重新验证', 'need_verify': True}), 401
    
    # 可选：验证 IP 一致性（增强安全性）
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    # 注意：由于 Cloudflare 可能使用不同边缘节点，IP 可能变化，暂不强制验证
    # if token_data['ip'] != client_ip:
    #     return jsonify({'success': False, 'error': 'IP 不匹配', 'need_verify': True}), 401
    
    # 清除验证token（一次性使用）
    del export_verify_tokens[verify_token]

    if not group_ids:
        return jsonify({'success': False, 'error': '请选择要导出的分组'})

    # 获取选中分组下的所有账号
    all_lines = []
    total_count = 0
    for group_id in group_ids:
        group = get_group_by_id(group_id)
        if not group:
            continue

        if group['name'] == '临时邮箱':
            # 临时邮箱分组从 temp_emails 表获取数据
            temp_emails = load_temp_emails()
            if temp_emails:
                all_lines.append(group['name'])

                gptmail_list = [te for te in temp_emails if te.get('provider', 'gptmail') == 'gptmail']
                duckmail_list = [te for te in temp_emails if te.get('provider') == 'duckmail']
                cloudflare_list = [te for te in temp_emails if te.get('provider') == 'cloudflare']

                if gptmail_list:
                    all_lines.append('[gptmail]')
                    for te in gptmail_list:
                        all_lines.append(te['email'])
                        total_count += 1

                if duckmail_list:
                    all_lines.append('[duckmail]')
                    for te in duckmail_list:
                        duckmail_password = decrypt_data(te.get('duckmail_password', '')) if te.get('duckmail_password') else ''
                        all_lines.append(f"{te['email']}----{duckmail_password}")
                        total_count += 1

                if cloudflare_list:
                    all_lines.append('[cloudflare]')
                    for te in cloudflare_list:
                        cloudflare_jwt = decrypt_data(te.get('cloudflare_jwt', '')) if te.get('cloudflare_jwt') else ''
                        all_lines.append(f"{te['email']}----{cloudflare_jwt}")
                        total_count += 1
        else:
            accounts = load_accounts(group_id)
            if accounts:
                all_lines.append(group['name'])
                for acc in accounts:
                    line = format_account_export_line(acc)
                    all_lines.append(line)
                    total_count += 1

    if total_count == 0:
        return jsonify({'success': False, 'error': '选中的分组下没有邮箱账号'})

    # 记录审计日志
    log_audit('export', 'selected_groups', ','.join(map(str, group_ids)), f"导出选中分组的 {total_count} 个账号")

    content = '\n'.join(all_lines)

    # 生成文件名
    filename = f"selected_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    encoded_filename = quote(filename)

    # 返回文件下载响应
    return Response(
        content,
        mimetype='text/plain; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.route('/api/export/verify', methods=['POST'])
@login_required
def api_generate_export_verify_token():
    """生成导出验证token（二次验证）"""
    data = request.json
    password = data.get('password', '')

    # 验证密码
    db = get_db()
    cursor = db.execute("SELECT value FROM settings WHERE key = 'login_password'")
    result = cursor.fetchone()

    if not result:
        return jsonify({'success': False, 'error': '系统配置错误'})

    stored_password = result[0]
    if not verify_password(password, stored_password):
        return jsonify({'success': False, 'error': '密码错误'})

    # 生成一次性验证token
    verify_token = secrets.token_urlsafe(32)
    
    # 使用 IP + 时间戳 作为用户标识（因为 session cookie 可能不可靠）
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip:
        client_ip = client_ip.split(',')[0].strip()
    
    # 存储到内存字典（设置5分钟过期）
    import time
    export_verify_tokens[verify_token] = {
        'ip': client_ip,
        'expires': time.time() + 300  # 5分钟有效期
    }
    
    # 清理过期的 token
    current_time = time.time()
    expired_tokens = [k for k, v in export_verify_tokens.items() if v['expires'] < current_time]
    for token in expired_tokens:
        del export_verify_tokens[token]

    return jsonify({'success': True, 'verify_token': verify_token})


# ==================== 邮箱账号 API ====================

@app.route('/api/accounts', methods=['GET'])
@login_required
def api_get_accounts():
    """获取所有账号"""
    group_id = request.args.get('group_id', type=int)
    accounts = load_accounts(group_id)

    # 获取每个账号的最后刷新状态
    db = get_db()

    # 返回时隐藏敏感信息
    safe_accounts = []
    for acc in accounts:
        last_refresh_log = get_latest_account_refresh_log(acc['id'], db)
        safe_accounts.append(serialize_account_summary(acc, last_refresh_log))
    return jsonify({'success': True, 'accounts': safe_accounts})


@app.route('/api/external/accounts', methods=['GET'])
@csrf_exempt
@api_key_required
def api_external_get_accounts():
    """对外 API：通过 API Key 获取邮箱账号列表"""
    group_id = request.args.get('group_id', type=int)
    accounts = load_accounts(group_id)
    db = get_db()

    safe_accounts = []
    for acc in accounts:
        last_refresh_log = get_latest_account_refresh_log(acc['id'], db)
        safe_accounts.append(
            serialize_account_summary(
                acc,
                last_refresh_log,
                include_client_meta=False,
                include_imap_meta=False
            )
        )

    return jsonify({
        'success': True,
        'total': len(safe_accounts),
        'accounts': safe_accounts
    })


# ==================== 标签 API ====================

@app.route('/api/tags', methods=['GET'])
@login_required
def api_get_tags():
    """获取所有标签"""
    return jsonify({'success': True, 'tags': get_tags()})


@app.route('/api/tags', methods=['POST'])
@login_required
def api_add_tag():
    """添加标签"""
    data = request.json
    name = sanitize_input(data.get('name', '').strip(), max_length=50)
    color = data.get('color', '#1a1a1a')

    if not name:
        return jsonify({'success': False, 'error': '标签名称不能为空'})

    tag_id = add_tag(name, color)
    if tag_id:
        return jsonify({'success': True, 'tag': {'id': tag_id, 'name': name, 'color': color}})
    else:
        return jsonify({'success': False, 'error': '标签名称已存在'})


@app.route('/api/tags/<int:tag_id>', methods=['DELETE'])
@login_required
def api_delete_tag(tag_id):
    """删除标签"""
    if delete_tag(tag_id):
        return jsonify({'success': True, 'message': '标签已删除'})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/accounts/tags', methods=['POST'])
@login_required
def api_batch_manage_tags():
    """批量管理账号标签"""
    data = request.json
    account_ids = data.get('account_ids', [])
    tag_id = data.get('tag_id')
    action = data.get('action')  # add, remove

    if not account_ids or not tag_id or not action:
        return jsonify({'success': False, 'error': '参数不完整'})

    count = 0
    for acc_id in account_ids:
        if action == 'add':
            if add_account_tag(acc_id, tag_id):
                count += 1
        elif action == 'remove':
            if remove_account_tag(acc_id, tag_id):
                count += 1

    return jsonify({'success': True, 'message': f'成功处理 {count} 个账号'})


@app.route('/api/accounts/batch-update-group', methods=['POST'])
@login_required
def api_batch_update_account_group():
    """批量更新账号分组"""
    data = request.json
    account_ids = data.get('account_ids', [])
    group_id = data.get('group_id')

    if not account_ids:
        return jsonify({'success': False, 'error': '请选择要修改的账号'})

    if not group_id:
        return jsonify({'success': False, 'error': '请选择目标分组'})

    # 验证分组存在
    group = get_group_by_id(group_id)
    if not group:
        return jsonify({'success': False, 'error': '目标分组不存在'})

    # 检查是否是临时邮箱分组（系统保留分组）
    if group.get('is_system'):
        return jsonify({'success': False, 'error': '不能移动到系统分组'})

    # 批量更新
    db = get_db()
    try:
        placeholders = ','.join('?' * len(account_ids))
        db.execute(f'''
            UPDATE accounts SET group_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
        ''', [group_id] + account_ids)
        db.commit()
        return jsonify({
            'success': True,
            'message': f'已将 {len(account_ids)} 个账号移动到「{group["name"]}」分组'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/accounts/batch-update-forwarding', methods=['POST'])
@login_required
def api_batch_update_account_forwarding():
    """批量更新账号转发状态"""
    data = request.json or {}
    account_ids = data.get('account_ids', [])

    if 'forward_enabled' not in data:
        return jsonify({'success': False, 'error': '缺少转发状态参数'})

    raw_forward_enabled = data.get('forward_enabled')
    if isinstance(raw_forward_enabled, str):
        forward_enabled = raw_forward_enabled.strip().lower() in {'1', 'true', 'yes', 'on'}
    else:
        forward_enabled = bool(raw_forward_enabled)

    result = update_accounts_forwarding_by_ids(account_ids, forward_enabled)
    if not result.get('success'):
        return jsonify(result)

    action_label = '开启' if forward_enabled else '关闭'
    updated_count = result.get('updated_count', 0)
    unchanged_count = result.get('unchanged_count', 0)

    if updated_count and unchanged_count:
        message = f'已为 {updated_count} 个账号{action_label}转发，{unchanged_count} 个账号已处于该状态'
    elif updated_count:
        message = f'已为 {updated_count} 个账号{action_label}转发'
    elif unchanged_count:
        message = f'所选 {unchanged_count} 个账号已处于{action_label}转发状态'
    else:
        message = '没有可更新的账号'

    return jsonify({
        'success': True,
        'message': message,
        'updated_count': updated_count,
        'updated_accounts': result.get('updated_accounts', []),
        'unchanged_count': unchanged_count,
        'missing_ids': result.get('missing_ids', []),
    })



@app.route('/api/accounts/search', methods=['GET'])
@login_required
def api_search_accounts():
    """全局搜索账号"""
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'success': True, 'accounts': []})

    db = get_db()
    # 支持搜索邮箱、备注和标签
    cursor = db.execute('''
        SELECT DISTINCT a.*, g.name as group_name, g.color as group_color
        FROM accounts a
        LEFT JOIN groups g ON a.group_id = g.id
        LEFT JOIN account_aliases aa ON a.id = aa.account_id
        LEFT JOIN account_tags at ON a.id = at.account_id
        LEFT JOIN tags t ON at.tag_id = t.id
        WHERE a.email LIKE ? OR a.remark LIKE ? OR t.name LIKE ? OR aa.alias_email LIKE ?
        ORDER BY a.created_at DESC
    ''', (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))

    rows = cursor.fetchall()
    safe_accounts = []
    for row in rows:
        acc = dict(row)
        aliases = get_account_aliases(acc['id'])
        # 加载账号标签
        acc['tags'] = get_account_tags(acc['id'])
        
        # 查询该账号最后一次刷新记录
        refresh_cursor = db.execute('''
            SELECT status, error_message, created_at
            FROM account_refresh_logs
            WHERE account_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (acc['id'],))
        last_refresh_log = refresh_cursor.fetchone()

        safe_accounts.append({
            'id': acc['id'],
            'email': acc['email'],
            'aliases': aliases,
            'alias_count': len(aliases),
            'client_id': acc['client_id'][:8] + '...' if len(acc['client_id']) > 8 else acc['client_id'],
            'group_id': acc['group_id'],
            'group_name': acc['group_name'] if acc['group_name'] else '默认分组',
            'group_color': acc['group_color'] if acc['group_color'] else '#666666',
            'remark': acc['remark'] if acc['remark'] else '',
            'status': acc['status'] if acc['status'] else 'active',
            'account_type': acc.get('account_type', 'outlook'),
            'provider': acc.get('provider', 'outlook'),
            'forward_enabled': bool(acc.get('forward_enabled')),
            'created_at': acc['created_at'] if acc['created_at'] else '',
            'updated_at': acc['updated_at'] if acc['updated_at'] else '',
            'tags': acc['tags'],
            'last_refresh_at': acc.get('last_refresh_at', ''),
            'last_refresh_status': last_refresh_log['status'] if last_refresh_log else None,
            'last_refresh_error': last_refresh_log['error_message'] if last_refresh_log else None
        })

    return jsonify({'success': True, 'accounts': safe_accounts})


@app.route('/api/accounts/<int:account_id>', methods=['GET'])
@login_required
def api_get_account(account_id):
    """获取单个账号详情"""
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'})
    
    return jsonify({
        'success': True,
        'account': {
            'id': account['id'],
            'email': account['email'],
            'password': account['password'],
            'client_id': account['client_id'],
            'refresh_token': account['refresh_token'],
            'account_type': account.get('account_type', 'outlook'),
            'provider': account.get('provider', 'outlook'),
            'imap_host': account.get('imap_host', ''),
            'imap_port': account.get('imap_port', 993),
            'imap_password': account.get('imap_password', ''),
            'aliases': account.get('aliases', []),
            'alias_count': account.get('alias_count', 0),
            'matched_alias': account.get('matched_alias', ''),
            'forward_enabled': bool(account.get('forward_enabled')),
            'forward_last_checked_at': account.get('forward_last_checked_at', ''),
            'group_id': account.get('group_id'),
            'group_name': account.get('group_name', '默认分组'),
            'remark': account.get('remark', ''),
            'status': account.get('status', 'active'),
            'created_at': account.get('created_at', ''),
            'updated_at': account.get('updated_at', '')
        }
    })


def parse_alias_payload(raw_aliases: Any) -> List[str]:
    if isinstance(raw_aliases, str):
        values = raw_aliases.replace(',', '\n').splitlines()
    elif isinstance(raw_aliases, (list, tuple, set)):
        values = list(raw_aliases)
    else:
        values = []
    return [str(value or '').strip() for value in values if str(value or '').strip()]


@app.route('/api/accounts/<int:account_id>/aliases', methods=['GET'])
@login_required
def api_get_account_aliases_endpoint(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'}), 404
    return jsonify({
        'success': True,
        'account_id': account_id,
        'email': account.get('email', ''),
        'aliases': account.get('aliases', []),
    })


@app.route('/api/accounts/<int:account_id>/aliases', methods=['PUT'])
@login_required
def api_replace_account_aliases_endpoint(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'success': False, 'error': '账号不存在'}), 404

    data = request.json or {}
    aliases = parse_alias_payload(data.get('aliases', []))
    db = get_db()
    success, cleaned_aliases, errors = replace_account_aliases(account_id, account.get('email', ''), aliases, db)
    if not success:
        db.rollback()
        return jsonify({'success': False, 'error': '；'.join(errors), 'errors': errors}), 400

    db.commit()
    return jsonify({
        'success': True,
        'message': f'已保存 {len(cleaned_aliases)} 个别名',
        'aliases': cleaned_aliases,
    })


@app.route('/api/accounts', methods=['POST'])
@login_required
def api_add_account():
    """添加账号"""
    data = request.json
    account_str = data.get('account_string', '')
    group_id = data.get('group_id', 1)
    account_format = data.get('account_format', 'client_id_refresh_token')
    provider = data.get('provider', 'outlook')
    forward_enabled = bool(data.get('forward_enabled', False))
    imap_host = (data.get('imap_host', '') or '').strip()
    try:
        imap_port = int(data.get('imap_port', 993) or 993)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'IMAP 端口无效'})
    
    if not account_str:
        return jsonify({'success': False, 'error': '请输入账号信息'})
    
    # 支持批量导入（多行）
    lines = account_str.strip().split('\n')
    added = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parsed = parse_account_import(line, account_format, provider, imap_host, imap_port)
        if parsed:
            if add_account(
                parsed['email'],
                parsed.get('password', ''),
                parsed.get('client_id', ''),
                parsed.get('refresh_token', ''),
                group_id,
                '',
                parsed.get('account_type', 'outlook'),
                parsed.get('provider', provider),
                parsed.get('imap_host', ''),
                parsed.get('imap_port', 993),
                parsed.get('imap_password', ''),
                forward_enabled
            ):
                added += 1
    
    if added > 0:
        return jsonify({'success': True, 'message': f'成功添加 {added} 个账号'})
    else:
        return jsonify({'success': False, 'error': '没有新账号被添加（可能格式错误或已存在）'})


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
@login_required
def api_update_account(account_id):
    """更新账号"""
    data = request.json

    # 检查是否只更新状态
    if 'status' in data and len(data) == 1:
        # 只更新状态
        return api_update_account_status(account_id, data['status'])

    email_addr = data.get('email', '')
    password = data.get('password', '')
    client_id = data.get('client_id', '')
    refresh_token = data.get('refresh_token', '')
    account_type = data.get('account_type', 'outlook')
    provider = data.get('provider', 'outlook')
    imap_host = (data.get('imap_host', '') or '').strip()
    imap_port = data.get('imap_port', 993)
    imap_password = data.get('imap_password', '')
    group_id = data.get('group_id', 1)
    remark = sanitize_input(data.get('remark', ''), max_length=200)
    status = data.get('status', 'active')
    forward_enabled = bool(data.get('forward_enabled', False))
    aliases_provided = 'aliases' in data
    aliases = parse_alias_payload(data.get('aliases', [])) if aliases_provided else []

    provider_meta = get_provider_meta(provider, email_addr)
    is_outlook = (account_type == 'outlook') or provider_meta['key'] == 'outlook'
    if is_outlook:
        if not email_addr or not client_id or not refresh_token:
            return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})
        account_type = 'outlook'
        provider = 'outlook'
        imap_host = IMAP_SERVER_NEW
        imap_port = IMAP_PORT
        imap_password = ''
    else:
        if not email_addr or not imap_password:
            return jsonify({'success': False, 'error': '邮箱和 IMAP 密码不能为空'})
        if provider_meta['key'] == 'custom' and not imap_host:
            return jsonify({'success': False, 'error': '自定义 IMAP 必须填写服务器地址'})
        client_id = ''
        refresh_token = ''
        account_type = 'imap'
        provider = provider_meta['key']
        if provider != 'custom':
            imap_host = provider_meta.get('imap_host', '')
            imap_port = provider_meta.get('imap_port', 993)

    if False:
        return jsonify({'success': False, 'error': '邮箱、Client ID 和 Refresh Token 不能为空'})

    if aliases_provided:
        _, alias_errors = validate_account_aliases(account_id, email_addr, aliases)
        if alias_errors:
            return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})

    if update_account(
        account_id, email_addr, password, client_id, refresh_token, group_id, remark, status,
        account_type, provider, imap_host, imap_port, imap_password, forward_enabled
    ):
        cleaned_aliases = get_account_aliases(account_id)
        if aliases_provided:
            db = get_db()
            alias_success, cleaned_aliases, alias_errors = replace_account_aliases(account_id, email_addr, aliases, db)
            if not alias_success:
                db.rollback()
                return jsonify({'success': False, 'error': '；'.join(alias_errors), 'errors': alias_errors})
            db.commit()
        return jsonify({'success': True, 'message': '账号更新成功', 'aliases': cleaned_aliases})
    else:
        return jsonify({'success': False, 'error': '更新失败'})


def api_update_account_status(account_id: int, status: str):
    """只更新账号状态"""
    db = get_db()
    try:
        db.execute('''
            UPDATE accounts
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, account_id))
        db.commit()
        return jsonify({'success': True, 'message': '状态更新成功'})
    except Exception:
        return jsonify({'success': False, 'error': '更新失败'})


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def api_delete_account(account_id):
    """删除账号"""
    if delete_account_by_id(account_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/accounts/email/<email_addr>', methods=['DELETE'])
@login_required
def api_delete_account_by_email(email_addr):
    """根据邮箱地址删除账号"""
    if delete_account_by_email(email_addr):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '删除失败'})


@app.route('/api/accounts/batch-delete', methods=['POST'])
@login_required
def api_batch_delete_accounts():
    """批量删除账号"""
    data = request.get_json(silent=True) or {}
    result = delete_accounts_by_ids(data.get('account_ids') or [])
    if not result.get('success'):
        return jsonify({'success': False, 'error': result.get('error', '删除失败')})

    deleted_count = result.get('deleted_count', 0)
    missing_ids = result.get('missing_ids', [])
    message = f'已删除 {deleted_count} 个账号'
    if missing_ids:
        message += f'，忽略 {len(missing_ids)} 个不存在的账号'

    return jsonify({
        'success': True,
        'message': message,
        'deleted_count': deleted_count,
        'deleted_accounts': result.get('deleted_accounts', []),
        'missing_ids': missing_ids,
    })


# ==================== 账号刷新 API ====================
