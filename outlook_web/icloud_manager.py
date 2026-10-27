"""Per-account coordination, persistent retries and one-shot iCloud scheduling."""

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from random import SystemRandom

from outlook_web.icloud_client import ICloudClient
from outlook_web.icloud_codes import fetch_code_response, fresh_code
from outlook_web.icloud_protocol import AppleProtocolError
from outlook_web.icloud_store import ICloudStore


class ICloudManager:
    def __init__(self, database, cipher_factory, client_factory=ICloudClient, clock=time.time, proxy_resolver=None):
        self.database, self.cipher_factory = database, cipher_factory
        self.client_factory, self.clock = client_factory, clock
        self.proxy_resolver = proxy_resolver
        self.scheduler = None
        self.locks, self.running = {}, set()
        self.guard = threading.Lock()
        self.stopped = threading.Event()
        self.epoch = 0
        self.random = SystemRandom()

    @contextmanager
    def store(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield ICloudStore(db, self.cipher_factory())
        finally:
            db.close()

    def lock(self, account_id):
        with self.guard:
            return self.locks.setdefault(account_id, threading.Lock())

    def current(self, account_id, version, epoch, automatic=False):
        if self.stopped.is_set() or epoch != self.epoch:
            return False
        with self.store() as store:
            try:
                account = store.account(account_id)
            except ValueError:
                return False
            return (account['config_version'] == version and store.allowed(account)
                    and (not automatic or account['auto_login']))

    def next_renewal(self, channel, expires_at):
        now = self.clock()
        interval = self.random.randint(240, 360) if channel == 'account' else 12 * 60
        if expires_at:
            interval = min(interval, max(1, (expires_at - now) * .8))
        return now + interval

    def restore(self, scheduler):
        self.scheduler = scheduler
        self.stopped.clear()
        with self.store() as store:
            ids = [row[0] for row in store.db.execute('SELECT id FROM icloud_accounts')]
        return any([self.schedule(account_id) for account_id in ids])

    def schedule(self, account_id):
        if self.scheduler is None or self.stopped.is_set():
            return False
        added = False
        with self.store() as store:
            try:
                account = store.account(account_id)
            except ValueError:
                account = None
            for channel in ('web', 'account'):
                job_id = f'icloud:{account_id}:{channel}'
                job = self.scheduler.get_job(job_id)
                if job:
                    self.scheduler.remove_job(job_id)
                if account is None or not store.allowed(account):
                    continue
                session = store.session(account_id, channel)
                if session['state'] in {'manual_required', 'verification_required'}:
                    continue
                if session['state'] != 'connected' and not account['auto_login'] and session['mode'] != 'renew':
                    continue
                when = session['next_attempt'] or self.clock()
                self.scheduler.add_job(self.dispatch, 'date', run_date=datetime.fromtimestamp(max(self.clock(), when), timezone.utc),
                    args=[account_id, channel], id=job_id, replace_existing=True, misfire_grace_time=None)
                added = True
        return added

    def dispatch(self, account_id, channel):
        with self.guard:
            if account_id in self.running or self.stopped.is_set():
                # The existing worker will re-arm both channels on exit.
                return
            self.running.add(account_id)

        def run():
            try:
                with self.store() as store:
                    account = store.account(account_id)
                    row = store.session(account_id, channel)
                if row['next_attempt'] and row['next_attempt'] > self.clock():
                    return
                if row['mode'] == 'renew' and row['snapshot_enc']:
                    self.perform(account_id, channel, 'renew', expected_version=account['config_version'], expected_revision=row['revision'])
                elif account['auto_login']:
                    self.auto_login(account_id, channel)
            except (ValueError, AppleProtocolError):
                pass  # Stable status is saved by perform/auto_login; no secret exception text.
            finally:
                with self.guard:
                    self.running.discard(account_id)
                self.schedule(account_id)

        threading.Thread(target=run, name=f'icloud-{account_id}', daemon=True).start()

    def _load(self, account_id, channel, automatic=False, *, allow_unreadable_snapshot=False):
        with self.store() as store:
            account = store.account(account_id)
            if not store.allowed(account) or automatic and not account['auto_login']:
                raise ValueError('主号或绑定收信账号已停用')
            row = store.session(account_id, channel)
            try:
                snapshot = store.unseal(row['snapshot_enc']) if row['snapshot_enc'] else None
            except ValueError:
                if not allow_unreadable_snapshot:
                    store.save_session(account_id, channel, account['config_version'], row['revision'],
                        state='manual_required', next_attempt=None, last_error='configuration_required')
                    raise
                snapshot = None
            proxy = ''
            if account['mailbox_account_id']:
                mailbox = store.db.execute('SELECT * FROM accounts WHERE id=?', (account['mailbox_account_id'],)).fetchone()
                if mailbox and 'proxy_url' in mailbox.keys():
                    proxy = self.proxy_resolver(dict(mailbox), store.db) if self.proxy_resolver else mailbox['proxy_url'] or ''
            return account, row, snapshot, proxy

    def _client(self, account, channel, snapshot, proxy, automatic=False, expires_at=None):
        epoch = self.epoch
        client = self.client_factory(account['apple_id'], account['region'], channel, snapshot=snapshot, proxy=proxy,
            cancelled=lambda: not self.current(account['id'], account['config_version'], epoch, automatic))
        client.expires_at = expires_at
        return client

    def _success(self, account, row, client):
        client.check()
        now = self.clock()
        state = client.snapshot()['state']
        with self.store() as store:
            return store.save_session(account['id'], row['channel'], account['config_version'], row['revision'], client.snapshot(),
                state=state, failures=0, last_error='', last_attempt=now,
                last_success=now if state == 'connected' else row['last_success'], expires_at=client.expires_at,
                next_attempt=self.next_renewal(row['channel'], client.expires_at) if state == 'connected' else None,
                mode='renew' if state == 'connected' else 'login')

    def _failure(self, account, row, error, client=None, login=False):
        if isinstance(error, AppleProtocolError) and error.kind == 'cancelled':
            return
        kind = error.kind if isinstance(error, AppleProtocolError) else 'configuration_required'
        failures = row['failures'] + 1
        mode = 'login' if login else row['mode']
        state = row['state']
        if kind in {'authentication_failed', 'account_action_required', 'configuration_required', 'invalid_response', 'session_identity_mismatch'}:
            state, next_attempt = 'manual_required', None
        elif kind in {'session_expired', 'verification_required'}:
            state, mode = 'expired', 'login'
            next_attempt = self.clock() if account['auto_login'] else None
        else:
            if login:
                delay = min(30, 5 * 2 ** min(failures - 1, 3)) * 60 + self.random.randint(0, 60)
                state = 'retry'
            else:
                delay = (2, 4, 8, 16, 30)[min(failures - 1, 4)] * 60
            delay = max(delay, getattr(error, 'retry_after', 0))
            next_attempt = self.clock() + delay
        with self.store() as store:
            store.save_session(account['id'], row['channel'], account['config_version'], row['revision'],
                client.snapshot() if client else None, state=state, mode=mode, failures=failures,
                next_attempt=next_attempt, last_attempt=self.clock(), last_error=kind,
                expires_at=client.expires_at if client and client.expires_at else row['expires_at'])

    def perform(self, account_id, channel, action, password='', code='', expected_version=None, expected_revision=None):
        with self.lock(account_id):
            account, row, snapshot, proxy = self._load(account_id, channel, allow_unreadable_snapshot=action == 'login')
            if ((expected_version is not None and expected_version != account['config_version'])
                    or (expected_revision is not None and expected_revision != row['revision'])):
                raise AppleProtocolError('cancelled')
            client = self._client(account, channel, snapshot, proxy, expires_at=row['expires_at'])
            try:
                if action == 'login':
                    client.login(password)
                elif action == 'verify':
                    client.verify(code)
                elif action == 'renew':
                    client.renew()
                else:
                    raise ValueError('登录操作无效')
                if not self._success(account, row, client):
                    raise AppleProtocolError('cancelled')
                return client.snapshot()['state']
            except (AppleProtocolError, ValueError) as error:
                if action == 'verify' and isinstance(error, AppleProtocolError) and error.kind == 'invalid_code':
                    with self.store() as store:
                        store.save_session(account_id, channel, account['config_version'], row['revision'], client.snapshot(),
                            state='verification_required', next_attempt=None, last_error='invalid_code')
                else:
                    self._failure(account, row, error, client, login=action in {'login', 'verify'})
                raise
            finally:
                client.close()
                self.schedule(account_id)

    def auto_login(self, account_id, channel):
        account, row, snapshot, proxy = self._load(account_id, channel, automatic=True)
        client = self._client(account, channel, snapshot, proxy, automatic=True, expires_at=row['expires_at'])
        try:
            with self.store() as store:
                password, url = store.unseal(account['password_enc']), store.unseal(account['code_url_enc'])
            client.check()
            baseline = fetch_code_response(url)
            client.check()
            started = self.clock()
            with self.lock(account_id):
                client.login(password)
            if client.snapshot()['state'] == 'verification_required':
                for _ in range(18):
                    if self.stopped.wait(5):
                        raise AppleProtocolError('cancelled')
                    # Waiting for a code never holds the account operation lock.
                    if client.cancelled():
                        raise AppleProtocolError('cancelled')
                    current = fetch_code_response(url)
                    code = fresh_code(current, baseline, started, self.clock())
                    if code:
                        with self.lock(account_id):
                            client.deadline = time.monotonic() + 30
                            client.check()
                            client.verify(code)
                        break
                else:
                    raise AppleProtocolError('temporary_failure', 'verify_code')
            if not self._success(account, row, client):
                raise AppleProtocolError('cancelled')
        except (ValueError, AppleProtocolError) as error:
            # Retrieval failures are temporary; credential decryption is manual.
            if isinstance(error, ValueError) and not isinstance(error, AppleProtocolError) and '解密' not in str(error):
                error = AppleProtocolError('temporary_failure', 'verify_code', retry_after=getattr(error, 'retry_after', 0))
            self._failure(account, row, error, client, login=True)
            raise error from None
        finally:
            client.close()

    def aliases(self, account_id, action='sync', alias_id=None, label='', note='', confirmed=False):
        with self.lock(account_id):
            account, row, snapshot, proxy = self._load(account_id, 'web')
            client = self._client(account, 'web', snapshot, proxy, expires_at=row['expires_at'])
            try:
                if action == 'create':
                    candidate = client.generate()
                    with self.store() as store:
                        with store.db:
                            store.require_version(account_id, account['config_version'])
                            store.stage(account_id, candidate, label, note)
                    reserved = client.mutate('reserve', {'hme': candidate, 'label': label, 'note': note})
                    with self.store() as store:
                        with store.db:
                            store.require_version(account_id, account['config_version'])
                            store.reserved_identity(account_id, candidate, reserved)
                elif action in {'deactivate', 'delete'}:
                    with self.store() as store:
                        alias = store.alias(account_id, alias_id)
                    if alias['state'] == 'pending':
                        raise ValueError('待核对地址请先同步，不能重复写入')
                    if action == 'delete' and (not confirmed or alias['state'] != 'inactive'):
                        raise ValueError('请先停用地址并明确确认永久删除')
                    try:
                        client.mutate(action, {'anonymousId': alias['remote_id']})
                    except AppleProtocolError as error:
                        if error.kind in {'temporary_failure', 'invalid_response'}:
                            with self.store() as store:
                                with store.db:
                                    store.require_version(account_id, account['config_version'])
                                    store.db.execute("UPDATE icloud_hme_aliases SET state='pending',pending_action=? WHERE id=?", (action, alias_id))
                                    store.project(account_id)
                        raise
                    with self.store() as store:
                        with store.db:
                            store.require_version(account_id, account['config_version'])
                            store.db.execute('UPDATE icloud_hme_aliases SET state=? WHERE id=?', ('inactive' if action == 'deactivate' else 'removed', alias_id))
                            store.project(account_id)
                    self._success(account, row, client)
                    return
                elif action != 'sync':
                    raise ValueError('隐藏地址操作无效')
                directory = client.directory()
                client.check()
                with self.store() as store:
                    with store.db:
                        store.require_version(account_id, account['config_version'])
                        store.sync(account_id, directory)
                self._success(account, row, client)
            except AppleProtocolError as error:
                self._failure(account, row, error, client)
                raise
            finally:
                client.close()
                self.schedule(account_id)

    def stop(self):
        self.stopped.set()
        self.epoch += 1
        self.scheduler = None
