"""Standalone Outlook token refresh strategy settings."""


@app.route('/refresh-strategy')
@login_required
def refresh_strategy_management_page():
    return index()


@app.route('/api/refresh-strategy', methods=['GET', 'PUT'])
@login_required
def api_refresh_strategy_settings():
    if request.method == 'GET':
        enforce_legacy_refresh_retirement()
        legacy_enabled = get_setting('enable_scheduled_refresh', 'true').lower() == 'true'
        legacy_retired = get_setting(REFRESH_LEGACY_RETIRED_SETTING, 'false').lower() == 'true'
        return jsonify({
            'success': True,
            'strategy': {
                'mode': get_refresh_strategy_mode(),
                'expiry_window_days': get_refresh_token_expiry_window_days(),
                'default_lifetime_days': get_refresh_token_default_lifetime_days(),
                'include_missing_anchor': get_refresh_token_include_missing_anchor(),
                'legacy_enabled': legacy_enabled,
                'legacy_retired': legacy_retired,
                'legacy_available': legacy_enabled and not legacy_retired,
                'legacy_use_cron': get_setting('use_cron_schedule', 'false').lower() == 'true',
                'legacy_cron': get_setting('refresh_cron', '0 2 * * *'),
                'legacy_interval_days': get_setting('refresh_interval_days', '30'),
            },
        })

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': '刷新策略设置必须为对象'}), 400

    mode = str(data.get('mode', '')).strip().lower()
    if mode not in REFRESH_STRATEGY_MODES:
        return jsonify({'success': False, 'error': '刷新模式必须是 expiry、legacy 或 disabled'}), 400
    enforce_legacy_refresh_retirement()
    if mode == 'legacy' and not is_legacy_refresh_strategy_available():
        return jsonify({'success': False, 'error': '旧刷新策略已关闭，不能重新选择或启用'}), 400

    try:
        expiry_window_days = int(data.get('expiry_window_days'))
        default_lifetime_days = int(data.get('default_lifetime_days'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'RT 天数配置必须是数字'}), 400
    if not 1 <= expiry_window_days <= 3650:
        return jsonify({'success': False, 'error': 'RT 提前刷新天数必须在 1-3650 天之间'}), 400
    if not 1 <= default_lifetime_days <= 3650:
        return jsonify({'success': False, 'error': 'RT 默认寿命必须在 1-3650 天之间'}), 400

    include_missing_anchor = str(data.get('include_missing_anchor', '')).strip().lower()
    if include_missing_anchor not in ('true', 'false'):
        return jsonify({'success': False, 'error': '未知到期时间纳入设置必须是 true 或 false'}), 400

    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        settings_to_save = [
            ('refresh_strategy_mode', mode),
            ('refresh_token_expires_within_days', str(expiry_window_days)),
            ('refresh_token_default_lifetime_days', str(default_lifetime_days)),
            ('refresh_token_include_missing_anchor', include_missing_anchor),
        ]
        if mode != 'legacy':
            settings_to_save.extend((
                ('enable_scheduled_refresh', 'false'),
                (REFRESH_LEGACY_RETIRED_SETTING, 'true'),
            ))
        for key, value in settings_to_save:
            db.execute(
                'INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)',
                (key, value),
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({'success': False, 'error': f'保存刷新策略失败：{str(exc)}'}), 500

    reload_token_refresh_job()
    return jsonify({'success': True, 'message': '刷新策略已保存'})
