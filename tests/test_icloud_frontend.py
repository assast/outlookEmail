import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run_frontend(scenario):
    script = r'''
const fs = require('fs'), vm = require('vm');
const elements = new Map(), buttons = [{disabled:false}, {disabled:false}], requests = [];
function element(id) {
    if (!elements.has(id)) elements.set(id, {value:'', checked:false, hidden:false, dataset:{},
        innerHTML:'', textContent:'', querySelectorAll:() => buttons, addEventListener() {}});
    return elements.get(id);
}
const context = {console, Date, Set, document:{getElementById:element, addEventListener(){}},
    escapeHtml:value=>String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    showModal(){}, hideModal(){}, showConfirmModal:async()=>true,
    fetch:async (url, options)=>{requests.push({url, options}); return {ok:true,json:async()=>({success:true,accounts:[],mailboxes:[]})};},
    requests, element, buttons};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/index/14-icloud.js','utf8'),context);
(async()=>{console.log(JSON.stringify(await vm.runInContext(SCENARIO,context)));})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('SCENARIO', json.dumps(scenario))
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_state_read_is_local_and_does_not_post_or_fill_secrets():
    result = run_frontend('''(async()=>{await showICloudManagement(); return {requests:requests.map(r=>[r.url,r.options.method]),
        password:element('icPassword').value, codeUrl:element('icCodeUrl').value};})()''')
    assert result == {'requests': [['/api/icloud/accounts', 'GET']], 'password': '', 'codeUrl': ''}


def test_duplicate_clicks_are_locked_and_failures_preserve_inputs():
    result = run_frontend('''(async()=>{
        element('icAppleId').value='test@example.com'; element('icPassword').value=' secret ';
        element('icAliasLabel').value='my label'; let finish;
        fetch=async()=>{requests.push('post'); return new Promise(resolve=>{finish=resolve;});};
        const first=saveICloudAccount({preventDefault(){}}); await Promise.resolve();
        const busy=icloudUI.busy && buttons.every(b=>b.disabled);
        await saveICloudAccount({preventDefault(){}});
        finish({ok:false,json:async()=>({success:false,error:'upstream failed'})}); await first;
        return {count:requests.length,busy,unlocked:!icloudUI.busy && buttons.every(b=>!b.disabled),
            password:element('icPassword').value,label:element('icAliasLabel').value,error:element('icloudMessage').textContent};
    })()''')
    assert result == {'count': 1, 'busy': True, 'unlocked': True, 'password': ' secret ', 'label': 'my label', 'error': 'upstream failed'}


def test_ui_labels_and_managed_aliases_preserve_separate_mailbox_health():
    source = (ROOT / 'static/js/index/14-icloud.js').read_text()
    template = (ROOT / 'templates/partials/index/dialogs-icloud.html').read_text()
    assert 'IMAP 是否可收信需在邮箱列表单独验证' in source
    assert '等待验证码' in source and '需要人工处理' in source
    assert '永久删除后无法恢复' in source and '自动重登仍开启' in source
    assert 'autocomplete="one-time-code"' in template


def test_successful_login_displays_mfa_state_and_clears_attempt_secrets():
    result = run_frontend('''(async()=>{
        const account={id:1,apple_id:'a@example.com',region:'global',enabled:1,auto_login:false,
            mailbox_account_id:null,sessions:[{channel:'web',state:'verification_required',failures:0}],aliases:[]};
        icloudUI.accounts=[account]; icloudUI.selected=1;
        element('icLoginPassword').value='secret'; element('icChannel').value='web';
        fetch=async(url,options)=>{requests.push({url,method:options.method});
            return {ok:true,json:async()=>options.method==='POST'?{success:true,state:'verification_required'}:
                {success:true,accounts:[account],mailboxes:[]}};};
        await icAction('login'); return {message:element('icloudMessage').textContent,
            state:element('icloudSessions').innerHTML,password:element('icLoginPassword').value,requests};
    })()''')
    assert '等待验证码' in result['state'] and '双重验证' in result['message']
    assert result['password'] == ''
    assert result['requests'] == [{'url': '/api/icloud/accounts/1/login', 'method': 'POST'}, {'url': '/api/icloud/accounts', 'method': 'GET'}]
