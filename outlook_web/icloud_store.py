"""SQLite ownership and encrypted state for native iCloud management."""

import json
import sqlite3
import time


class ManagedAddressUnavailable(ValueError):
    pass


def init_icloud_schema(db):
    statements = [
        '''CREATE TABLE IF NOT EXISTS icloud_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apple_id TEXT NOT NULL COLLATE NOCASE, region TEXT NOT NULL CHECK(region IN ('global','cn')),
            enabled INTEGER NOT NULL DEFAULT 1, mailbox_account_id INTEGER,
            binding_lost INTEGER NOT NULL DEFAULT 0, remark TEXT NOT NULL DEFAULT '',
            password_enc TEXT NOT NULL DEFAULT '', code_url_enc TEXT NOT NULL DEFAULT '',
            auto_login INTEGER NOT NULL DEFAULT 0, config_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE(apple_id, region), FOREIGN KEY(mailbox_account_id) REFERENCES accounts(id) ON DELETE SET NULL)''',
        '''CREATE TABLE IF NOT EXISTS icloud_sessions (
            account_id INTEGER NOT NULL, channel TEXT NOT NULL CHECK(channel IN ('web','account')),
            snapshot_enc TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'signed_out',
            revision INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL, expires_at REAL, last_success REAL, last_attempt REAL,
            last_error TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'login',
            PRIMARY KEY(account_id,channel), FOREIGN KEY(account_id) REFERENCES icloud_accounts(id) ON DELETE CASCADE)''',
        '''CREATE TABLE IF NOT EXISTS icloud_hme_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER,
            remote_id TEXT NOT NULL, address TEXT NOT NULL COLLATE NOCASE,
            label TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', forward_to TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL, conflict TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT 'web',
            pending_action TEXT NOT NULL DEFAULT '',
            UNIQUE(account_id,remote_id), FOREIGN KEY(account_id) REFERENCES icloud_accounts(id) ON DELETE SET NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_icloud_hme_address ON icloud_hme_aliases(address)',
    ]
    for statement in statements:
        db.execute(statement)
    if 'pending_action' not in {row[1] for row in db.execute('PRAGMA table_info(icloud_hme_aliases)')}:
        db.execute("ALTER TABLE icloud_hme_aliases ADD COLUMN pending_action TEXT NOT NULL DEFAULT ''")
    retained_columns = {row[1] for row in db.execute('PRAGMA table_info(retained_normal_mail_messages)')}
    if retained_columns and 'recipient_evidence' not in retained_columns:
        db.execute("ALTER TABLE retained_normal_mail_messages ADD COLUMN recipient_evidence TEXT NOT NULL DEFAULT ''")
    if 'icloud_alias_id' not in {row[1] for row in db.execute('PRAGMA table_info(account_aliases)')}:
        db.execute('ALTER TABLE account_aliases ADD COLUMN icloud_alias_id INTEGER DEFAULT NULL')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_icloud_source ON account_aliases(icloud_alias_id) WHERE icloud_alias_id IS NOT NULL')
    db.execute('''CREATE TRIGGER IF NOT EXISTS icloud_primary_insert BEFORE INSERT ON accounts
        WHEN EXISTS (SELECT 1 FROM icloud_hme_aliases WHERE address=LOWER(TRIM(NEW.email)))
          AND NOT EXISTS (SELECT 1 FROM accounts WHERE LOWER(email)=LOWER(TRIM(NEW.email)))
        BEGIN SELECT RAISE(ABORT, 'iCloud 托管地址不能作为普通主邮箱导入'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS icloud_primary_update BEFORE UPDATE OF email ON accounts
        WHEN LOWER(NEW.email)!=LOWER(OLD.email)
          AND EXISTS (SELECT 1 FROM icloud_hme_aliases WHERE address=LOWER(TRIM(NEW.email)))
        BEGIN SELECT RAISE(ABORT, 'iCloud 托管地址不能改为普通主邮箱'); END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS icloud_mailbox_status AFTER UPDATE OF status ON accounts
        WHEN OLD.status != NEW.status BEGIN
        UPDATE icloud_accounts SET config_version=config_version+1 WHERE mailbox_account_id=NEW.id;
        DELETE FROM account_aliases WHERE icloud_alias_id IN
          (SELECT h.id FROM icloud_hme_aliases h JOIN icloud_accounts a ON a.id=h.account_id
           WHERE a.mailbox_account_id=NEW.id) AND NEW.status != 'active'; END''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS icloud_mailbox_delete BEFORE DELETE ON accounts BEGIN
        UPDATE icloud_accounts SET binding_lost=1,config_version=config_version+1 WHERE mailbox_account_id=OLD.id;
        DELETE FROM account_aliases WHERE icloud_alias_id IN
          (SELECT h.id FROM icloud_hme_aliases h JOIN icloud_accounts a ON a.id=h.account_id
           WHERE a.mailbox_account_id=OLD.id); END''')


class ICloudStore:
    def __init__(self, db, cipher):
        self.db, self.cipher = db, cipher

    def seal(self, value):
        return 'enc:' + self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def unseal(self, value):
        try:
            if not isinstance(value, str) or not value.startswith('enc:'):
                raise ValueError
            return json.loads(self.cipher.decrypt(value[4:].encode()).decode())
        except Exception:
            raise ValueError('iCloud 凭据无法解密，请重新配置或登录') from None

    def account(self, account_id):
        row = self.db.execute('SELECT * FROM icloud_accounts WHERE id=?', (account_id,)).fetchone()
        if not row:
            raise ValueError('iCloud 主号不存在')
        return dict(row)

    def allowed(self, account):
        if not account['enabled'] or account['binding_lost']:
            return False
        if account['mailbox_account_id']:
            mailbox = self.db.execute('SELECT status FROM accounts WHERE id=?', (account['mailbox_account_id'],)).fetchone()
            return bool(mailbox and mailbox['status'] == 'active')
        return True

    def public(self, account):
        result = {key: account[key] for key in ('id', 'apple_id', 'region', 'enabled', 'mailbox_account_id', 'remark', 'auto_login', 'config_version', 'binding_lost')}
        result['password_configured'] = bool(account['password_enc'])
        result['code_url_configured'] = bool(account['code_url_enc'])
        result['working_allowed'] = self.allowed(account)
        result['sessions'] = [dict(row) for row in self.db.execute('''SELECT channel,state,revision,failures,
            next_attempt,expires_at,last_success,last_attempt,last_error,mode FROM icloud_sessions WHERE account_id=?''', (account['id'],))]
        result['aliases'] = [dict(row) for row in self.db.execute('SELECT * FROM icloud_hme_aliases WHERE account_id=? ORDER BY id DESC', (account['id'],))]
        return result

    def save_account(self, data, account_id=None):
        old = self.account(account_id) if account_id else {
            'apple_id': '', 'region': 'global', 'enabled': 1, 'mailbox_account_id': None,
            'binding_lost': 0, 'remark': '', 'auto_login': 0, 'password_enc': '', 'code_url_enc': '',
        }
        item = dict(old)
        for key in ('apple_id', 'region', 'remark'):
            if key in data:
                if not isinstance(data[key], str):
                    raise ValueError('主号字段格式无效')
                item[key] = data[key].strip()
        item['apple_id'] = item['apple_id'].lower()
        if not item['apple_id'] or '@' not in item['apple_id'] or item['region'] not in {'global', 'cn'}:
            raise ValueError('请填写有效 Apple ID 和区域')
        for key in ('enabled', 'auto_login'):
            if key in data:
                if type(data[key]) not in (bool, int) or data[key] not in (0, 1):
                    raise ValueError('开关格式无效')
                item[key] = int(data[key])
        if 'mailbox_account_id' in data:
            binding = data['mailbox_account_id']
            if binding is not None and (type(binding) is not int or binding <= 0):
                raise ValueError('收信绑定无效')
            if binding and not self.db.execute('SELECT id FROM accounts WHERE id=?', (binding,)).fetchone():
                raise ValueError('收信账号不存在')
            item['mailbox_account_id'] = binding
            item['binding_lost'] = 0
        for field in ('password', 'code_url'):
            if data.get('clear_' + field) is True:
                item[field + '_enc'] = ''
            elif data.get(field) != '' and field in data:
                if not isinstance(data[field], str):
                    raise ValueError('秘密字段格式无效')
                if field == 'code_url':
                    from outlook_web.icloud_codes import validate_code_url
                    validate_code_url(data[field])
                item[field + '_enc'] = self.seal(data[field])
        if item['auto_login'] and not (item['password_enc'] and item['code_url_enc']):
            raise ValueError('开启自动重登需要保存密码和接码 URL')
        changed = any(item[key] != old[key] for key in (
            'apple_id', 'region', 'enabled', 'auto_login', 'mailbox_account_id', 'binding_lost', 'password_enc', 'code_url_enc'))
        credentials_changed = any(item[key] != old[key] for key in ('apple_id', 'region', 'password_enc', 'code_url_enc'))
        keys = ('apple_id', 'region', 'enabled', 'mailbox_account_id', 'binding_lost', 'remark', 'auto_login', 'password_enc', 'code_url_enc')
        try:
            with self.db:
                if account_id:
                    self.db.execute('UPDATE icloud_accounts SET ' + ','.join(key + '=?' for key in keys) + ',config_version=config_version+? WHERE id=?',
                                    [item[key] for key in keys] + [int(changed), account_id])
                    if (item['region'], item['apple_id']) != (old['region'], old['apple_id']):
                        self.db.execute("UPDATE icloud_sessions SET snapshot_enc='',state='signed_out',revision=revision+1,next_attempt=NULL WHERE account_id=?", (account_id,))
                        self.db.execute("UPDATE icloud_hme_aliases SET state='removed' WHERE account_id=?", (account_id,))
                    elif credentials_changed:
                        self.db.execute("UPDATE icloud_sessions SET failures=0,next_attempt=NULL,last_error='',state=CASE WHEN state='manual_required' THEN 'signed_out' ELSE state END WHERE account_id=?", (account_id,))
                else:
                    account_id = self.db.execute('INSERT INTO icloud_accounts (' + ','.join(keys) + ') VALUES (' + ','.join('?' for _ in keys) + ')', [item[key] for key in keys]).lastrowid
                    for channel in ('web', 'account'):
                        self.db.execute('INSERT INTO icloud_sessions(account_id,channel) VALUES (?,?)', (account_id, channel))
                self.project(account_id)
        except sqlite3.IntegrityError:
            raise ValueError('相同区域的 Apple ID 已存在') from None
        return self.account(account_id)

    def project(self, account_id):
        """Called in the caller's short transaction; never performs network I/O."""
        account = self.account(account_id)
        self.db.execute('DELETE FROM account_aliases WHERE icloud_alias_id IN (SELECT id FROM icloud_hme_aliases WHERE account_id=?)', (account_id,))
        mailbox = self.db.execute('SELECT * FROM accounts WHERE id=?', (account['mailbox_account_id'],)).fetchone()
        recognized = set()
        if mailbox:
            recognized.add(mailbox['email'].lower())
            recognized.update(row[0].lower() for row in self.db.execute('SELECT alias_email FROM account_aliases WHERE account_id=? AND icloud_alias_id IS NULL', (mailbox['id'],)))
        for row in self.db.execute('SELECT * FROM icloud_hme_aliases WHERE account_id=?', (account_id,)).fetchall():
            conflict = ''
            if row['state'] != 'active':
                continue
            if not mailbox or not self.allowed(account):
                conflict = '收信未绑定或账号已停用'
            elif row['forward_to'].lower() not in recognized:
                conflict = '转发目标与收信账号不一致'
            elif (self.db.execute('SELECT 1 FROM accounts WHERE LOWER(email)=?', (row['address'],)).fetchone()
                  or self.db.execute('SELECT 1 FROM temp_emails WHERE LOWER(email)=?', (row['address'],)).fetchone()
                  or self.db.execute('SELECT 1 FROM account_aliases WHERE LOWER(alias_email)=?', (row['address'],)).fetchone()
                  or self.db.execute("SELECT 1 FROM icloud_hme_aliases WHERE address=? AND account_id IS NOT NULL AND account_id!=? AND state='active'", (row['address'], account_id)).fetchone()):
                conflict = '地址被主邮箱、手工别名或其他主号占用'
            else:
                self.db.execute('INSERT INTO account_aliases(account_id,alias_email,icloud_alias_id) VALUES (?,?,?)', (mailbox['id'], row['address'], row['id']))
            self.db.execute('UPDATE icloud_hme_aliases SET conflict=? WHERE id=?', (conflict, row['id']))

    def sync(self, account_id, directory):
        if directory.channel != 'web' or not directory.authoritative:
            raise ValueError('仅完整 Web HME 目录可作为同步快照')
        with self.db:
            self.account(account_id)
            self.db.execute("UPDATE icloud_hme_aliases SET state='removed' WHERE account_id=? AND NOT (state='pending' AND pending_action='create')", (account_id,))
            for alias in directory.aliases:
                previous = self.db.execute('SELECT address FROM icloud_hme_aliases WHERE account_id=? AND remote_id=?', (account_id, alias.remote_id)).fetchone()
                if previous and previous['address'] != alias.address:
                    raise ValueError('上游地址身份发生变化，目录未覆盖，请人工核对')
                self.db.execute('''INSERT INTO icloud_hme_aliases(account_id,remote_id,address,label,note,forward_to,state)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(account_id,remote_id) DO UPDATE SET
                    address=excluded.address,label=excluded.label,note=excluded.note,forward_to=excluded.forward_to,state=excluded.state,pending_action='' ''',
                    (account_id, alias.remote_id, alias.address, alias.label, alias.note, alias.forward_to, 'active' if alias.active else 'inactive'))
                self.db.execute("DELETE FROM icloud_hme_aliases WHERE account_id=? AND address=? AND remote_id LIKE 'pending:%'", (account_id, alias.address))
            self.project(account_id)

    def stage(self, account_id, address, label, note):
        with self.db:
            self.db.execute('''INSERT INTO icloud_hme_aliases(account_id,remote_id,address,label,note,state,pending_action)
                VALUES (?,?,?,?,?,'pending','create') ON CONFLICT(account_id,remote_id) DO UPDATE SET state='pending',pending_action='create' ''',
                (account_id, 'pending:' + address, address, label, note))
            self.project(account_id)

    def reserved_identity(self, account_id, address, result):
        alias = result.get('hme') if isinstance(result, dict) else None
        if not isinstance(alias, dict):
            return  # Keep the candidate pending until a complete directory confirms it.
        if not isinstance(alias.get('hme'), str) or alias['hme'].lower() != address:
            from outlook_web.icloud_protocol import AppleProtocolError
            raise AppleProtocolError('invalid_response', 'directory')
        remote_id = alias.get('anonymousId')
        if isinstance(remote_id, str) and remote_id:
            existing = self.db.execute('SELECT address FROM icloud_hme_aliases WHERE account_id=? AND remote_id=?', (account_id, remote_id)).fetchone()
            if existing:
                if existing['address'] != address:
                    from outlook_web.icloud_protocol import AppleProtocolError
                    raise AppleProtocolError('invalid_response', 'directory')
                self.db.execute('DELETE FROM icloud_hme_aliases WHERE account_id=? AND remote_id=?', (account_id, 'pending:' + address))
                return
            self.db.execute("UPDATE icloud_hme_aliases SET remote_id=? WHERE account_id=? AND remote_id=? AND state='pending'",
                            (remote_id, account_id, 'pending:' + address))

    def alias(self, account_id, alias_id):
        row = self.db.execute('SELECT * FROM icloud_hme_aliases WHERE id=? AND account_id=?', (alias_id, account_id)).fetchone()
        if not row:
            raise ValueError('隐藏地址不属于该主号')
        return dict(row)

    def session(self, account_id, channel):
        if not isinstance(channel, str) or channel not in {'web', 'account'}:
            raise ValueError('通道无效')
        row = self.db.execute('SELECT * FROM icloud_sessions WHERE account_id=? AND channel=?', (account_id, channel)).fetchone()
        if not row:
            raise ValueError('会话不存在')
        return dict(row)

    def require_version(self, account_id, version):
        # Acquire a short write transaction before publishing a remote result.
        if not self.db.execute('UPDATE icloud_accounts SET config_version=config_version WHERE id=? AND config_version=?',
                               (account_id, version)).rowcount:
            from outlook_web.icloud_protocol import AppleProtocolError
            raise AppleProtocolError('cancelled')

    def save_session(self, account_id, channel, version, revision, snapshot=None, **status):
        allowed = {'state', 'failures', 'next_attempt', 'expires_at', 'last_success', 'last_attempt', 'last_error', 'mode'}
        if status.keys() - allowed:
            raise ValueError('会话状态字段无效')
        if snapshot is not None:
            status['snapshot_enc'] = self.seal(snapshot)
        with self.db:
            cursor = self.db.execute('UPDATE icloud_sessions SET revision=revision+1,' + ','.join(key + '=?' for key in status) +
                ' WHERE account_id=? AND channel=? AND revision=? AND EXISTS (SELECT 1 FROM icloud_accounts WHERE id=? AND config_version=?)',
                list(status.values()) + [account_id, channel, revision, account_id, version])
        return cursor.rowcount == 1

    def takeover(self, account_id, logout=False):
        with self.db:
            self.db.execute('UPDATE icloud_accounts SET config_version=config_version+1 WHERE id=?', (account_id,))
            if logout:
                self.db.execute("UPDATE icloud_sessions SET snapshot_enc='',state='signed_out',revision=revision+1,failures=0,next_attempt=NULL,expires_at=NULL,last_error='' WHERE account_id=?", (account_id,))
        return self.account(account_id)

    def delete(self, account_id):
        with self.db:
            self.account(account_id)
            self.db.execute('DELETE FROM account_aliases WHERE icloud_alias_id IN (SELECT id FROM icloud_hme_aliases WHERE account_id=?)', (account_id,))
            self.db.execute("UPDATE icloud_hme_aliases SET state='removed',account_id=NULL WHERE account_id=?", (account_id,))
            self.db.execute('DELETE FROM icloud_accounts WHERE id=?', (account_id,))

    def resolve(self, address):
        """None is ordinary; an unavailable managed address raises, never falls back."""
        rows = self.db.execute('SELECT * FROM icloud_hme_aliases WHERE address=?', (address,)).fetchall()
        if not rows:
            return None
        for row in rows:
            mapping = self.db.execute('SELECT account_id FROM account_aliases WHERE icloud_alias_id=?', (row['id'],)).fetchone()
            if row['account_id'] and row['state'] == 'active' and not row['conflict'] and mapping:
                account = self.account(row['account_id'])
                if self.allowed(account):
                    return {'mailbox_account_id': mapping['account_id'], 'icloud_alias_id': row['id'], 'icloud_address': address}
        raise ManagedAddressUnavailable('托管 iCloud 隐藏地址不可用，请检查状态与收信绑定')
