"""Authenticated native iCloud management; never an API-key management surface."""

from outlook_web.icloud_manager import ICloudManager
from outlook_web.icloud_protocol import AppleProtocolError
from outlook_web.icloud_store import ICloudStore, ManagedAddressUnavailable
from outlook_web.icloud_mail import scan_isolated_mail


icloud_manager = ICloudManager(DATABASE, get_cipher, proxy_resolver=get_account_proxy_url)


def icloud_store():
    return ICloudStore(get_db(), get_cipher())


def icloud_payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('请求内容必须是 JSON 对象')
    return data


def fetch_icloud_isolated_emails(account, folder, skip, top, local_options=None):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as ScanTimeout
    primary = dict(account)
    address = primary.pop('icloud_address')
    primary['_icloud_scan_address'] = address
    deadline = time.monotonic() + get_mail_fetch_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='icloud-mail-scan')

    def bounded(callback, *args, **kwargs):
        def execute():
            with app.app_context():
                return callback(*args, **kwargs)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'success': False}
        future = executor.submit(execute)
        try:
            return future.result(timeout=remaining)
        except ScanTimeout:
            future.cancel()
            return {'success': False, 'scan_incomplete': True}

    try:
        folders = [folder] if local_options is not None or folder != 'all' else ['inbox', 'junkemail']
        results = []
        for selected in folders:
            if local_options is not None:
                fetch = lambda offset, batch: bounded(fetch_retained_normal_mail_list, primary, selected, offset, batch, **local_options)
                detail = None
            else:
                fetch = lambda offset, batch: bounded(fetch_account_folder_emails, primary, selected, offset, batch,
                    get_account_proxy_url(primary), get_account_proxy_failover_urls(primary))
                def detail(item):
                    response = bounded(fetch_email_detail_for_account, primary, item['id'],
                        'graph' if item.get('id_mode') == 'graph' else 'imap', item.get('folder', selected), item.get('id_mode', ''))
                    return response.get('email', {}) if response.get('success') else {}
            result = scan_isolated_mail(fetch, address, 0 if len(folders) > 1 else skip,
                skip + top if len(folders) > 1 else top, deadline=deadline, detail=detail)
            results.append(result)
            if not result.get('success'):
                return result
        if len(results) == 1:
            return results[0]
        items = [item for result in results for item in result.get('emails', [])]
        items.sort(key=lambda item: retained_mail_received_at_sort(item.get('date')), reverse=True)
        return dict(results[0], emails=items[skip:skip + top], has_more=any(result.get('has_more') for result in results) or len(items) > skip + top,
                    isolated_address=address)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


@app.errorhandler(ManagedAddressUnavailable)
def icloud_address_unavailable(error):
    return jsonify({'success': False, 'error': str(error), 'code': 'ICLOUD_ADDRESS_UNAVAILABLE'}), 404


def icloud_status(account_id):
    store = icloud_store()
    return store.public(store.account(account_id))


def icloud_wake(account_id):
    if scheduler_instance is None:
        init_scheduler()
    else:
        icloud_manager.schedule(account_id)


@app.route('/api/icloud/accounts', methods=['GET', 'POST'])
@login_required
def api_icloud_accounts():
    store = icloud_store()
    if request.method == 'GET':
        accounts = [store.public(dict(row)) for row in store.db.execute('SELECT * FROM icloud_accounts ORDER BY id')]
        mailboxes = [dict(row) for row in store.db.execute('SELECT id,email,status FROM accounts ORDER BY email')]
        return jsonify({'success': True, 'accounts': accounts, 'mailboxes': mailboxes})
    try:
        data = icloud_payload()
        account = store.save_account(data)
        icloud_wake(account['id'])
        return jsonify({'success': True, 'account': icloud_status(account['id'])}), 201
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.route('/api/icloud/accounts/<int:account_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_icloud_account(account_id):
    try:
        store = icloud_store()
        if request.method == 'PUT':
            data = icloud_payload()
            store.save_account(data, account_id)
            icloud_wake(account_id)
        elif request.method == 'DELETE':
            if icloud_payload().get('confirm') is not True:
                raise ValueError('请确认删除本地主号；不会删除 Apple 地址或收信账号')
            store.delete(account_id)
            icloud_manager.schedule(account_id)
            return jsonify({'success': True})
        return jsonify({'success': True, 'account': icloud_status(account_id)})
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.route('/api/icloud/accounts/<int:account_id>/<action>', methods=['POST'])
@login_required
def api_icloud_session_action(account_id, action):
    if action not in {'login', 'verify', 'logout'}:
        return jsonify({'success': False, 'error': '操作不存在'}), 404
    try:
        data = icloud_payload()
        channel = data.get('channel', 'web')
        store = icloud_store()
        store.session(account_id, channel)
        if action == 'logout':
            account = store.takeover(account_id, logout=True)
            icloud_wake(account_id)
            return jsonify({'success': True, 'account': icloud_status(account_id),
                            'message': '已退出；自动重登仍开启，后续将重新登录' if account['auto_login'] else '已退出'})
        if action == 'login':
            account = store.takeover(account_id)
            password = data.get('password', '')
            if not password and account['password_enc']:
                password = store.unseal(account['password_enc'])
        else:
            password = ''
        state = icloud_manager.perform(account_id, channel, action, password=password, code=data.get('code', ''))
        icloud_wake(account_id)
        return jsonify({'success': True, 'state': state, 'account': icloud_status(account_id)})
    except AppleProtocolError as error:
        icloud_wake(account_id)
        return jsonify({'success': False, 'error': str(error), 'code': error.kind}), 409 if error.kind == 'cancelled' else 502
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.route('/api/icloud/accounts/<int:account_id>/aliases', methods=['GET', 'POST'])
@login_required
def api_icloud_aliases(account_id):
    try:
        if request.method == 'GET':
            return jsonify({'success': True, 'aliases': icloud_status(account_id)['aliases']})
        data = icloud_payload()
        if not isinstance(data.get('action', 'sync'), str):
            raise ValueError('隐藏地址操作无效')
        icloud_manager.aliases(account_id, action=data.get('action', 'sync'), alias_id=data.get('alias_id'),
                              label=str(data.get('label', '')), note=str(data.get('note', '')), confirmed=data.get('confirm') is True)
        return jsonify({'success': True, 'account': icloud_status(account_id)})
    except AppleProtocolError as error:
        return jsonify({'success': False, 'error': str(error), 'code': error.kind}), 502
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400


@app.after_request
def icloud_response_policy(response):
    if request.path.startswith('/api/icloud/'):
        response.headers['Cache-Control'] = 'no-store'
    # Explicit mailbox mutations are events, not a periodic account scan.
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and response.status_code < 400 and (
            request.path.startswith(('/api/accounts', '/api/batch', '/api/external/accounts'))):
        store = icloud_store()
        ids = [row[0] for row in store.db.execute('SELECT id FROM icloud_accounts WHERE mailbox_account_id IS NOT NULL OR binding_lost=1')]
        for account_id in ids:
            with store.db:
                store.project(account_id)
            icloud_wake(account_id)
    return response


if scheduler_instance is not None:
    icloud_manager.restore(scheduler_instance)
else:
    ensure_scheduler_started()
