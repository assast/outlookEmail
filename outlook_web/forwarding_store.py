"""Persistent notification destinations, source policies and delivery identities."""

import json
import re
import sqlite3
import time
from urllib.parse import urlparse


CHANNEL_FIELDS = {
    'smtp': ('recipient', 'host', 'port', 'username', 'password', 'from_email', 'use_tls', 'use_ssl'),
    'telegram': ('bot_token', 'chat_id', 'topic_id', 'proxy_url'),
    'wecom': ('webhook_url',),
    'feishu': ('webhook_url', 'sign_secret'),
}
SECRET_FIELDS = {'password', 'bot_token', 'webhook_url', 'sign_secret'}
DESTINATION_FIELDS = {'smtp': ('recipient',), 'telegram': ('chat_id', 'topic_id'),
                      'wecom': ('webhook_url',), 'feishu': ('webhook_url',)}
LEGACY_FIELDS = {
    'smtp': {'recipient': 'email_forward_recipient', **{f: 'smtp_' + f for f in CHANNEL_FIELDS['smtp'] if f != 'recipient'}},
    'telegram': {f: 'telegram_' + f for f in CHANNEL_FIELDS['telegram']},
    'wecom': {'webhook_url': 'wecom_webhook_url'},
    'feishu': {f: 'feishu_' + f for f in CHANNEL_FIELDS['feishu']},
}
LOG_TYPES = {'smtp': 'email', 'telegram': 'telegram', 'wecom': 'wecom', 'feishu': 'feishu'}
SCOPES = {'normal_default', 'group', 'account', 'cloudflare_worker', 'cloudflare_domain', 'cloudflare_address'}
UNFINISHED = ('pending', 'failed', 'blocked', 'sending')


def normalize_keywords(value):
    if not isinstance(value, str):
        raise ValueError('邮件关键词必须是文本')
    lines, seen = [], set()
    for line in value.splitlines():
        line = line.strip()
        if line and line.casefold() not in seen:
            lines.append(line)
            seen.add(line.casefold())
    return '\n'.join(lines)


def normalize_senders(value):
    if not isinstance(value, str):
        raise ValueError('发件人筛选必须是文本，每行填写一个完整邮箱地址')
    return '\n'.join(dict.fromkeys(normalize_address(line) for line in value.splitlines() if line.strip()))


def normalize_channel_selection(raw_channels):
    if isinstance(raw_channels, str):
        values = raw_channels.split(',')
    elif isinstance(raw_channels, (list, tuple, set)):
        values = raw_channels
    else:
        values = []
    aliases = {'email': 'smtp', 'smtp': 'smtp', 'tg': 'telegram', 'telegram': 'telegram',
               'wecom': 'wecom', 'wechatwork': 'wecom', 'qywx': 'wecom', 'feishu': 'feishu'}
    normalized = []
    for value in values:
        kind = aliases.get(str(value).strip().lower())
        if kind and kind not in normalized:
            normalized.append(kind)
    return normalized


def normalize_domain(value):
    raw = str(value or '').strip().lstrip('@').rstrip('.')
    try:
        domain = raw.encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise ValueError('请输入有效的完整域名') from None
    if len(domain) > 253 or '.' not in domain or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in domain.split('.')
    ):
        raise ValueError('请输入有效的完整域名，不支持通配符')
    return domain


def normalize_address(value):
    raw = str(value or '').strip().lower()
    if raw.count('@') != 1:
        raise ValueError('请输入单个完整邮箱地址')
    local, domain = raw.rsplit('@', 1)
    if not local or re.search(r'[\s<>,;*?\x00-\x1f]', local):
        raise ValueError('请输入单个完整邮箱地址，不支持通配符')
    return local + '@' + normalize_domain(domain)


def normalize_feishu_url(value):
    try:
        parsed = urlparse(value)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'open.feishu.cn'
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'/open-apis/bot/v2/hook/[A-Za-z0-9_-]+', parsed.path)
                 and not re.search(r'\s', value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('飞书 Webhook 必须是有效的 https://open.feishu.cn/open-apis/bot/v2/hook/ 地址')
    return 'https://open.feishu.cn' + parsed.path


def decode_config(row, decrypt):
    config = json.loads(row['config_json'])
    return {key: decrypt(value) if key in SECRET_FIELDS and value else value for key, value in config.items()}


def encode_config(config, encrypt):
    return json.dumps({key: encrypt(value) if key in SECRET_FIELDS and value else value
                       for key, value in config.items()}, ensure_ascii=False)


def merge_config(kind, draft, saved=None, validate=True):
    if not isinstance(kind, str) or kind not in CHANNEL_FIELDS or not isinstance(draft, dict):
        raise ValueError('通知类型或配置无效')
    if 'clear_sign_secret' in draft and not isinstance(draft['clear_sign_secret'], bool):
        raise ValueError('清除签名选项必须是布尔值')
    config = dict(saved or {})
    for key in CHANNEL_FIELDS[kind]:
        value = draft.get(key)
        if key in ('use_tls', 'use_ssl'):
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError('TLS/SSL 选项必须是布尔值')
                config[key] = value
        elif key == 'port':
            try:
                config[key] = int(value if value not in (None, '') else config.get(key, 465))
            except (TypeError, ValueError):
                if validate:
                    raise ValueError('SMTP 端口无效') from None
                config[key] = 0
        elif value is not None:
            if not isinstance(value, str):
                raise ValueError('渠道配置字段必须是文本')
            value = value.strip()
            if key not in SECRET_FIELDS or value:
                config[key] = value
        config.setdefault(key, False if key == 'use_tls' else True if key == 'use_ssl' else '')
    if draft.get('clear_sign_secret') is True:
        config['sign_secret'] = ''
    if not validate:
        return config
    required = {'smtp': ('recipient', 'host'), 'telegram': ('bot_token', 'chat_id'),
                'wecom': ('webhook_url',), 'feishu': ('webhook_url',)}[kind]
    if any(not config.get(key) for key in required):
        raise ValueError('请补全该通知渠道的必填配置')
    if kind == 'smtp':
        if not 1 <= config['port'] <= 65535 or not (config.get('from_email') or config.get('username')):
            raise ValueError('请填写有效 SMTP 端口和发件地址')
    if kind == 'telegram' and config.get('topic_id') and not re.fullmatch(r'[1-9][0-9]*', config['topic_id']):
        raise ValueError('Telegram 话题 ID 必须为正整数')
    if kind == 'feishu':
        config['webhook_url'] = normalize_feishu_url(config['webhook_url'])
    if kind == 'wecom':
        parsed = urlparse(config['webhook_url'])
        if parsed.scheme != 'https' or not parsed.hostname:
            raise ValueError('企业微信 Webhook 必须为有效 HTTPS 地址')
    return config


def init_schema(db, encrypt, decrypt):
    original_factory = db.row_factory
    db.row_factory = sqlite3.Row
    statements = [
        '''CREATE TABLE IF NOT EXISTS notification_channels (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, type TEXT NOT NULL,
            config_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, legacy_key TEXT UNIQUE,
            target_version INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS forwarding_policies (
            id INTEGER PRIMARY KEY, scope_type TEXT NOT NULL, scope_id INTEGER NOT NULL DEFAULT 0,
            match_value TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(scope_type, scope_id, match_value))''',
        '''CREATE TABLE IF NOT EXISTS forwarding_policy_channels (
            policy_id INTEGER NOT NULL REFERENCES forwarding_policies(id) ON DELETE CASCADE,
            channel_id INTEGER NOT NULL REFERENCES notification_channels(id) ON DELETE RESTRICT,
            active_since REAL NOT NULL, PRIMARY KEY(policy_id, channel_id))''',
        '''CREATE TABLE IF NOT EXISTS forwarding_events (
            id INTEGER PRIMARY KEY, source_type TEXT NOT NULL, source_id INTEGER NOT NULL,
            message_id TEXT NOT NULL, email_address TEXT NOT NULL, received_at REAL NOT NULL,
            source_name TEXT NOT NULL DEFAULT '', group_id INTEGER, payload_json TEXT,
            created_at REAL NOT NULL, UNIQUE(source_type, source_id, email_address, message_id))''',
        '''CREATE TABLE IF NOT EXISTS forwarding_deliveries (
            id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES forwarding_events(id) ON DELETE CASCADE,
            channel_id INTEGER REFERENCES notification_channels(id) ON DELETE SET NULL,
            channel_name TEXT NOT NULL, channel_type TEXT NOT NULL, target_version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0, claim_token TEXT,
            error_message TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(event_id, channel_id))''',
        '''CREATE TABLE IF NOT EXISTS forwarding_attempts (
            id INTEGER PRIMARY KEY, delivery_id INTEGER NOT NULL REFERENCES forwarding_deliveries(id) ON DELETE CASCADE,
            status TEXT NOT NULL, error_message TEXT, created_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS cloudflare_forward_scan_state (
            worker_id INTEGER PRIMARY KEY REFERENCES cloudflare_channels(id) ON DELETE CASCADE,
            checkpoint_id INTEGER NOT NULL DEFAULT 0, active_since REAL NOT NULL,
            upper_id INTEGER, scan_next_id INTEGER, next_offset INTEGER NOT NULL DEFAULT 0, error_message TEXT,
            updated_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS forwarding_account_boundaries (
            account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, changed_at REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS forwarding_replay_requests (
            account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, requested_at REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_forwarding_delivery_due ON forwarding_deliveries(status, next_attempt_at)',
        'CREATE INDEX IF NOT EXISTS idx_forwarding_event_source ON forwarding_events(source_type, source_id)',
        '''CREATE TRIGGER IF NOT EXISTS forwarding_account_deleted AFTER DELETE ON accounts BEGIN
            DELETE FROM forwarding_policies WHERE scope_type='account' AND scope_id=OLD.id;
            UPDATE forwarding_deliveries SET status='cancelled', claim_token=NULL
                WHERE status IN ('pending','failed','blocked','sending') AND event_id IN
                (SELECT id FROM forwarding_events WHERE source_type='account' AND source_id=OLD.id);
        END''',
        '''CREATE TRIGGER IF NOT EXISTS forwarding_group_deleted AFTER DELETE ON groups BEGIN
            DELETE FROM forwarding_policies WHERE scope_type='group' AND scope_id=OLD.id;
        END''',
        '''CREATE TRIGGER IF NOT EXISTS forwarding_account_moved AFTER UPDATE OF group_id ON accounts
            WHEN OLD.group_id IS NOT NEW.group_id BEGIN
            INSERT OR REPLACE INTO forwarding_account_boundaries VALUES
                (NEW.id, (julianday('now')-2440587.5)*86400.0);
        END''',
        '''CREATE TRIGGER IF NOT EXISTS forwarding_group_moved AFTER UPDATE OF parent_id ON groups
            WHEN OLD.parent_id IS NOT NEW.parent_id BEGIN
            INSERT OR REPLACE INTO forwarding_account_boundaries
                SELECT id, (julianday('now')-2440587.5)*86400.0 FROM accounts WHERE group_id IN
                (WITH RECURSIVE tree(id) AS (SELECT NEW.id UNION ALL
                    SELECT g.id FROM groups g JOIN tree t ON g.parent_id=t.id) SELECT id FROM tree);
        END''',
    ]
    db.execute('SAVEPOINT forwarding_schema')
    try:
        for statement in statements:
            db.execute(statement)
        columns = {row['name'] for row in db.execute('PRAGMA table_info(forwarding_policies)')}
        if 'keywords' not in columns:
            db.execute("ALTER TABLE forwarding_policies ADD COLUMN keywords TEXT NOT NULL DEFAULT ''")
        if 'senders' not in columns:
            db.execute("ALTER TABLE forwarding_policies ADD COLUMN senders TEXT NOT NULL DEFAULT ''")
        marker = db.execute("SELECT value FROM settings WHERE key='source_forwarding_migrated'").fetchone()
        account_rules = db.execute("SELECT 1 FROM settings WHERE key='source_forwarding_account_rules_v3'").fetchone()
        if not marker or not account_rules:
            sync_legacy(db, encrypt, decrypt, initial=True)
            for key in ('source_forwarding_migrated', 'source_forwarding_channel_selection_v2',
                        'source_forwarding_account_switch_retired', 'source_forwarding_account_rules_v3'):
                db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (key, '1'))
        options = db.execute("SELECT 1 FROM settings WHERE key='source_forwarding_rule_options_v4'").fetchone()
        if not options:
            legacy_keywords = db.execute("SELECT value FROM settings WHERE key='forward_keywords'").fetchone()
            keywords = normalize_keywords(legacy_keywords['value'] if legacy_keywords else '')
            db.execute("UPDATE forwarding_policies SET keywords=? WHERE scope_type IN ('normal_default','group','account') AND mode='custom'", (keywords,))
            db.execute("INSERT INTO settings(key,value) VALUES('source_forwarding_rule_options_v4','1')")
        db.execute('RELEASE forwarding_schema')
    except Exception:
        db.execute('ROLLBACK TO forwarding_schema')
        db.execute('RELEASE forwarding_schema')
        raise
    finally:
        db.row_factory = original_factory


def get_channel(db, channel_id):
    row = db.execute('SELECT * FROM notification_channels WHERE id=?', (channel_id,)).fetchone()
    return dict(row) if row else None


def public_channel(db, row, decrypt):
    config = decode_config(row, decrypt)
    visible = {key: value for key, value in config.items() if key not in SECRET_FIELDS}
    visible.update({key + '_configured': bool(config.get(key)) for key in CHANNEL_FIELDS[row['type']] if key in SECRET_FIELDS})
    references = db.execute('SELECT COUNT(*) FROM forwarding_policy_channels WHERE channel_id=?', (row['id'],)).fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM forwarding_deliveries WHERE channel_id=? AND status IN ('pending','failed','blocked','sending')", (row['id'],)).fetchone()[0]
    return {**{key: row[key] for key in ('id', 'name', 'type', 'target_version', 'legacy_key')},
            'enabled': bool(row['enabled']), 'config': visible, 'reference_count': references, 'pending_count': pending}


def save_channel(db, data, encrypt, decrypt, channel_id=None):
    if not isinstance(data, dict):
        raise ValueError('通知渠道必须为对象')
    old = get_channel(db, channel_id) if channel_id is not None else None
    if channel_id is not None and not old:
        raise ValueError('通知渠道不存在')
    kind = data.get('type', old['type'] if old else '')
    if not isinstance(kind, str) or kind not in CHANNEL_FIELDS or old and old['type'] != kind:
        raise ValueError('通知类型无效或不允许修改')
    name = data.get('name', old['name'] if old else '')
    if not isinstance(name, str):
        raise ValueError('通知渠道名称必须是文本')
    name = name.strip()
    enabled = data.get('enabled', bool(old['enabled']) if old else True)
    if not name or len(name) > 100 or not isinstance(enabled, bool):
        raise ValueError('请填写有效名称和布尔启用状态')
    prior = decode_config(old, decrypt) if old else {}
    config = merge_config(kind, data.get('config', {}), prior)
    now = time.time()
    version = old['target_version'] if old else 1
    changed = bool(old and any(prior.get(key) != config.get(key) for key in DESTINATION_FIELDS[kind]))
    if changed:
        version += 1
    if old:
        db.execute('UPDATE notification_channels SET name=?, config_json=?, enabled=?, target_version=?, updated_at=? WHERE id=?',
                   (name, encode_config(config, encrypt), int(enabled), version, now, channel_id))
        if changed:
            db.execute("UPDATE forwarding_deliveries SET status='cancelled', claim_token=NULL, error_message='通知目的地已修改', updated_at=? WHERE channel_id=? AND status IN ('pending','failed','blocked')", (now, channel_id))
    else:
        channel_id = db.execute('INSERT INTO notification_channels(name,type,config_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                                (name, kind, encode_config(config, encrypt), int(enabled), now, now)).lastrowid
    if old and old['legacy_key']:
        for field, key in LEGACY_FIELDS[kind].items():
            value = config.get(field, '')
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if field in SECRET_FIELDS and value:
                value = encrypt(value)
            db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    return get_channel(db, channel_id)


def sync_legacy(db, encrypt, decrypt, initial=False, update_associations=True):
    settings = dict(db.execute('SELECT key,value FROM settings').fetchall())
    configured = []
    by_type = {}
    for kind, mapping in LEGACY_FIELDS.items():
        raw = {field: decrypt(settings.get(key, '')) if field in SECRET_FIELDS and settings.get(key) else settings.get(key, '')
               for field, key in mapping.items()}
        if kind == 'smtp':
            raw['use_ssl'] = str(raw.get('use_ssl', 'true')).lower() == 'true'
            raw['use_tls'] = str(raw.get('use_tls', 'false')).lower() == 'true'
        config = merge_config(kind, raw, validate=False)
        available = (bool(config.get('recipient') and config.get('host') and 1 <= config['port'] <= 65535) if kind == 'smtp' else
                     bool(config.get('bot_token') and config.get('chat_id')) if kind == 'telegram' else
                     bool(config.get('webhook_url')))
        if kind == 'feishu' and available:
            try:
                normalize_feishu_url(config['webhook_url'])
            except ValueError:
                available = False
        if available:
            configured.append(kind)
        row = db.execute('SELECT * FROM notification_channels WHERE legacy_key=?', (kind,)).fetchone()
        logged = db.execute('SELECT 1 FROM forward_logs WHERE channel=? LIMIT 1', (LOG_TYPES[kind],)).fetchone()
        if not row and (any(raw.get(f) for f in mapping if f not in ('port', 'use_ssl', 'use_tls')) or logged):
            name = '原有 ' + {'smtp': 'SMTP', 'telegram': 'Telegram', 'wecom': '企业微信', 'feishu': '飞书'}[kind]
            if db.execute('SELECT 1 FROM notification_channels WHERE name=?', (name,)).fetchone():
                name += '（兼容）'
            row_id = db.execute('INSERT INTO notification_channels(name,type,config_json,enabled,legacy_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                                (name, kind, encode_config(config, encrypt), int(kind in configured), kind, time.time(), time.time())).lastrowid
            row = db.execute('SELECT * FROM notification_channels WHERE id=?', (row_id,)).fetchone()
        if row:
            row = dict(row)
            old_config = decode_config(row, decrypt)
            if old_config != config:
                changed = any(old_config.get(k) != config.get(k) for k in DESTINATION_FIELDS[kind])
                db.execute('UPDATE notification_channels SET config_json=?, target_version=target_version+?, enabled=CASE WHEN ? THEN 1 ELSE enabled END, updated_at=? WHERE id=?',
                           (encode_config(config, encrypt), int(changed), not any(old_config.get(k) for k in DESTINATION_FIELDS[kind]) and kind in configured, time.time(), row['id']))
                if changed:
                    db.execute("UPDATE forwarding_deliveries SET status='cancelled', claim_token=NULL WHERE channel_id=? AND status IN ('pending','failed','blocked')", (row['id'],))
            by_type[kind] = row['id']
    if not update_associations:
        return
    raw_selection = str(settings.get('forward_channels', 'auto')).strip().lower()
    selected = configured if raw_selection in ('auto', '') else [] if raw_selection == 'none' else normalize_channel_selection(raw_selection)
    selected_ids = sorted({by_type[k] for k in selected if k in by_type and k in configured})
    default = get_policy(db, 'normal_default')
    auto_default = is_legacy_default(db, default)
    # A missing old default on an already migrated database means it was deleted.
    seed_missing = not initial or not settings.get('source_forwarding_migrated') or auto_default
    sync_legacy_account_policies(db, selected_ids, initial=initial, seed_missing=seed_missing)
    if initial and auto_default:
        db.execute('DELETE FROM forwarding_policies WHERE id=?', (default['id'],))


def is_legacy_default(db, policy):
    return (policy['id'] is not None and policy['updated_at'] == 0
            and all(get_channel(db, cid)['legacy_key'] for cid in policy['channel_ids']))


def sync_legacy_account_policies(db, channel_ids, *, initial, seed_missing):
    default = get_policy(db, 'normal_default')
    row = db.execute("SELECT value FROM settings WHERE key='forward_keywords'").fetchone()
    keywords = normalize_keywords(row['value'] if row else '')
    for account in db.execute('SELECT id,forward_enabled FROM accounts ORDER BY id').fetchall():
        enabled = bool(account['forward_enabled'])
        if not initial and not enabled:
            continue
        old = get_policy(db, 'account', account['id'])
        if old['id'] is not None and (old['updated_at'] != 0 or old['mode'] == 'inherit'):
            continue
        route = resolve_policy(db, account_id=account['id'])
        if old['id'] is None:
            if not seed_missing or route['path'][-1]['scope_type'] != 'normal_default':
                continue
            if default['id'] is not None and not is_legacy_default(db, default):
                continue
        targets = channel_ids if enabled else []
        mode = 'custom' if targets else 'off'
        if old['id'] is not None and old['mode'] == mode and old['channel_ids'] == targets and old['keywords'] == (keywords if targets else ''):
            continue
        since = {cid: old['active_since'].get(cid, route['active_since'].get(cid, 0)) for cid in targets}
        migrated = save_policy(db, {'scope_type': 'account', 'scope_id': account['id'],
                                    'mode': mode, 'channel_ids': targets, 'keywords': keywords})
        db.execute('UPDATE forwarding_policies SET updated_at=0 WHERE id=?', (migrated['id'],))
        for cid, active_since in since.items():
            db.execute('UPDATE forwarding_policy_channels SET active_since=? WHERE policy_id=? AND channel_id=?',
                       (active_since, migrated['id'], cid))


def normalize_scope(db, scope_type, scope_id=0, match_value=''):
    if not isinstance(scope_type, str) or scope_type not in SCOPES:
        raise ValueError('来源范围无效')
    try:
        scope_id = int(scope_id)
    except (ValueError, TypeError):
        raise ValueError('来源 ID 无效') from None
    if scope_type == 'normal_default':
        return scope_type, 0, ''
    table = 'accounts' if scope_type == 'account' else 'groups' if scope_type == 'group' else 'cloudflare_channels'
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (scope_id,)).fetchone()
    if not row:
        raise ValueError('指定的来源不存在')
    if scope_type == 'group' and row['is_system']:
        raise ValueError('临时邮箱请使用 CF 专用配置')
    match_value = normalize_domain(match_value) if scope_type == 'cloudflare_domain' else normalize_address(match_value) if scope_type == 'cloudflare_address' else ''
    return scope_type, scope_id, match_value


def policy_scopes(db, data):
    if not isinstance(data, dict):
        raise ValueError('来源配置必须为对象')
    raw_ids = data.get('scope_ids', [data.get('scope_id', 0)])
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError('请至少选择一个来源')
    if any(isinstance(value, bool) or not isinstance(value, (int, str)) for value in raw_ids):
        raise ValueError('来源 ID 无效')
    try:
        ids = sorted(set(int(value) for value in raw_ids))
    except ValueError:
        raise ValueError('来源 ID 无效') from None
    if data.get('scope_type') == 'normal_default' and ids != [0]:
        raise ValueError('普通默认配置只有一个来源')
    return [normalize_scope(db, data.get('scope_type'), source_id, data.get('match_value', '')) for source_id in ids]


def get_policy(db, scope_type, scope_id=0, match_value=''):
    row = db.execute('SELECT * FROM forwarding_policies WHERE scope_type=? AND scope_id=? AND match_value=?',
                     (scope_type, scope_id, match_value)).fetchone()
    value = dict(row) if row else {'id': None, 'scope_type': scope_type, 'scope_id': scope_id,
                                 'match_value': match_value, 'mode': 'off' if scope_type in ('normal_default', 'cloudflare_worker') else 'inherit', 'updated_at': 0, 'keywords': '', 'senders': ''}
    links = db.execute('SELECT channel_id,active_since FROM forwarding_policy_channels WHERE policy_id=? ORDER BY channel_id', (value['id'],)).fetchall() if row else []
    value['channel_ids'] = [r['channel_id'] for r in links]
    value['active_since'] = {r['channel_id']: r['active_since'] for r in links}
    return value


def selected_policies(db, ids):
    if not isinstance(ids, list) or not ids or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in ids):
        raise ValueError('请至少选择一条有效的转发规则')
    rows = [db.execute('SELECT scope_type,scope_id,match_value,mode FROM forwarding_policies WHERE id=?', (pid,)).fetchone() for pid in sorted(set(ids))]
    if any(row is None or row['mode'] == 'inherit' for row in rows):
        raise ValueError('部分转发规则已不存在，请刷新后重试')
    return [get_policy(db, row['scope_type'], row['scope_id'], row['match_value']) for row in rows]


def update_policies(db, data):
    if not isinstance(data, dict):
        raise ValueError('规则编辑必须为对象')
    changes = data.get('changes')
    if not isinstance(changes, dict) or not changes or changes.keys() - {'mode', 'channel_ids', 'keywords', 'senders'}:
        raise ValueError('请选择需要修改的通知方式、渠道或邮件条件，不能修改来源')
    if 'mode' in changes and changes['mode'] not in ('custom', 'off'):
        raise ValueError('编辑规则请选择指定渠道或关闭通知')
    policies = selected_policies(db, data.get('policy_ids'))
    if len({p['scope_type'] for p in policies}) != 1:
        raise ValueError('批量编辑仅支持同一来源范围的转发规则')
    return [save_policy(db, {**policy, **changes}) for policy in policies]


def save_policy(db, data, *, create_only=False):
    if not isinstance(data, dict):
        raise ValueError('来源配置必须为对象')
    scope = normalize_scope(db, data.get('scope_type'), data.get('scope_id', 0), data.get('match_value', ''))
    mode = data.get('mode')
    if mode not in ('inherit', 'custom', 'off') or mode == 'inherit' and scope[0] in ('normal_default', 'cloudflare_worker'):
        raise ValueError('通知模式无效')
    if create_only and mode == 'inherit':
        raise ValueError('新增转发规则请选择指定渠道或关闭通知')
    ids = data.get('channel_ids', [])
    if not isinstance(ids, list) or any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in ids):
        raise ValueError('渠道列表必须是渠道 ID 数组')
    ids = sorted(set(ids)) if mode == 'custom' else []
    if mode == 'custom' and not ids:
        raise ValueError('指定渠道时请至少选择一个渠道，或明确关闭通知')
    if any(not get_channel(db, cid) for cid in ids):
        raise ValueError('通知渠道不存在')
    old = get_policy(db, *scope)
    keywords = normalize_keywords(data.get('keywords', old['keywords'])) if mode == 'custom' else ''
    senders = normalize_senders(data.get('senders', old['senders'])) if mode == 'custom' else ''
    now = time.time()
    conflict_condition = " WHERE forwarding_policies.mode='inherit'" if create_only else ''
    result = db.execute('INSERT INTO forwarding_policies(scope_type,scope_id,match_value,mode,updated_at,keywords,senders) VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope_type,scope_id,match_value) DO UPDATE SET mode=excluded.mode,updated_at=excluded.updated_at,keywords=excluded.keywords,senders=excluded.senders' + conflict_condition, (*scope, mode, now, keywords, senders))
    if result.rowcount == 0:
        raise ValueError('该来源已有转发规则，请直接编辑；如需重新新增请先删除')
    pid = get_policy(db, *scope)['id']
    db.execute('DELETE FROM forwarding_policy_channels WHERE policy_id=?', (pid,))
    unchanged_filters = old['keywords'] == keywords and old['senders'] == senders
    for cid in ids:
        since = old['active_since'].get(cid, now) if old['mode'] == 'custom' and unchanged_filters else now
        db.execute('INSERT INTO forwarding_policy_channels VALUES(?,?,?)', (pid, cid, since))
    if scope[0] == 'normal_default':
        kinds = [r[0] for r in db.execute('SELECT legacy_key FROM notification_channels WHERE id IN (SELECT channel_id FROM forwarding_policy_channels WHERE policy_id=?) AND legacy_key IS NOT NULL', (pid,))]
        db.execute("INSERT INTO settings(key,value) VALUES('forward_channels',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (','.join(kinds) or 'none',))
    return get_policy(db, *scope)


def resolve_policy(db, *, account_id=None, worker_id=None, address=''):
    path = []
    eligible, reason, boundary = True, '', 0
    account = worker = None
    replay_requested_at = 0
    if account_id is not None:
        account = db.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        if not account:
            raise ValueError('邮箱账号不存在')
        address = account['email']
        eligible = account['status'] == 'active'
        reason = '' if eligible else '账号已停用'
        replay = db.execute('SELECT requested_at FROM forwarding_replay_requests WHERE account_id=?', (account_id,)).fetchone()
        replay_requested_at = replay[0] if replay else 0
        scopes = [('account', int(account_id), '')]
        group_id = account['group_id']
        while group_id:
            group = db.execute('SELECT * FROM groups WHERE id=?', (group_id,)).fetchone()
            if not group:
                break
            scopes.append(('group', group_id, ''))
            group_id = group['parent_id']
        scopes.append(('normal_default', 0, ''))
    else:
        address = normalize_address(address)
        worker = db.execute('SELECT * FROM cloudflare_channels WHERE id=?', (worker_id,)).fetchone()
        if not worker:
            raise ValueError('CF Worker 不存在')
        eligible = bool(worker['enabled'])
        reason = '' if eligible else 'CF Worker 已停用'
        scopes = [('cloudflare_address', int(worker_id), address),
                  ('cloudflare_domain', int(worker_id), address.rsplit('@', 1)[1]),
                  ('cloudflare_worker', int(worker_id), '')]
    selected = None
    for scope in scopes:
        current = get_policy(db, *scope)
        path.append({key: current[key] for key in ('scope_type', 'scope_id', 'match_value', 'mode')})
        boundary = max(boundary, current['updated_at'] if current['mode'] != 'custom' else 0)
        if current['mode'] != 'inherit':
            selected = current
            break
    ids = selected['channel_ids'] if selected and selected['mode'] == 'custom' else []
    if account and selected and selected['scope_type'] != 'account':
        moved = db.execute('SELECT changed_at FROM forwarding_account_boundaries WHERE account_id=?', (account_id,)).fetchone()
        boundary = max(boundary, moved[0] if moved else 0)
    since = {cid: max(boundary, selected['active_since'][cid]) for cid in ids}
    channels = [get_channel(db, cid) for cid in ids]
    blocked = [{'id': c['id'], 'reason': '通知渠道已停用'} for c in channels if not c['enabled']]
    return {'source_type': 'account' if account else 'cloudflare', 'source_id': int(account_id if account else worker_id),
            'email_address': address, 'eligible': eligible, 'reason': reason,
            'mode': selected['mode'] if selected else 'off', 'channel_ids': ids,
            'keywords': selected['keywords'] if selected else '',
            'senders': selected['senders'] if selected else '',
            'replay_requested_at': replay_requested_at,
            'path': path, 'active_since': since, 'blocked': blocked,
            'channels': [{'id': c['id'], 'name': c['name'], 'type': c['type'], 'enabled': bool(c['enabled'])} for c in channels]}


def worker_references(db, worker_id):
    policies = db.execute("SELECT COUNT(*) FROM forwarding_policies WHERE scope_type LIKE 'cloudflare_%' AND scope_id=? AND mode<>'inherit' AND (mode='custom' OR match_value<>'')", (worker_id,)).fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM forwarding_deliveries d JOIN forwarding_events e ON e.id=d.event_id WHERE e.source_type='cloudflare' AND e.source_id=? AND d.status IN ('pending','failed','blocked','sending')", (worker_id,)).fetchone()[0]
    return {'notification_reference_count': policies, 'pending_delivery_count': pending}
