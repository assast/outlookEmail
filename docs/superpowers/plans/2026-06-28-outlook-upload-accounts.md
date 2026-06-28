# Outlook 邮箱上传表与外部上传接口 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增独立表 `outlook_upload_accounts` 存储外部上传的 Outlook 账号/密码/是否授权（默认未授权），并提供 API Key 鉴权的外部上传接口 `POST /api/external/outlook/upload`（支持单条与批量），最后写入 `docs/api.md`。

**架构：** 沿用现有"分段 exec 到单一 `app` 全局命名空间"的结构。建表放在 `01_bootstrap.py` 的 `init_db()`；数据层函数放在 `02_groups_accounts.py`；外部路由放在 `07_routes_oauth_settings_external.py`，复用 `@csrf_exempt` + `@api_key_required` 与 `get_db()`/`db.commit()`；密码明文存储（按需求确认，不加密）；`email UNIQUE` + `INSERT OR IGNORE` 去重。

**技术栈：** Python 3 + Flask + sqlite3（标准库），测试用 `unittest` + Flask `test_client`（模块入口 `web_outlook_app`，见 `tests/conftest.py`）。

**设计文档：** `docs/superpowers/specs/2026-06-28-outlook-upload-accounts-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `outlook_web/segments/01_bootstrap.py` | 在 `init_db()` 内新增建表语句 + 索引 | 修改 |
| `outlook_web/segments/02_groups_accounts.py` | 新增数据层函数 `add_upload_account` / `add_upload_accounts_bulk` | 修改 |
| `outlook_web/segments/07_routes_oauth_settings_external.py` | 新增外部上传路由 `api_external_upload_outlook` | 修改 |
| `docs/api.md` | 汇总表新增一行 + 详情区新增小节 | 修改 |
| `tests/test_outlook_upload_accounts.py` | 新表 + 数据层 + 路由的单元/集成测试 | 创建 |

**重要背景（实现者必读）：**
- 所有 `outlook_web/segments/*.py` 在运行时被 `web_outlook_app.py` 用 `exec(code, globals())` 拼进**同一个** `globals()`。因此各段之间直接引用 `app`、`get_db`、`encrypt_data`、`api_key_required`、`csrf_exempt`、`jsonify`、`request` 等，**无需 import**。
- 测试通过 `import web_outlook_app` 拿到该聚合模块，所有函数/路由都是它的属性（如 `web_outlook_app.add_upload_account`、`web_outlook_app.app`）。
- `init_db()` 在 `01_bootstrap.py`，用自己的 `sqlite3.connect(DATABASE)`（变量名为 `conn` / `cursor`），结尾统一 `conn.commit()` / `conn.close()`。建表语句要加在迁移段（注释 `# 检查并添加缺失的列（数据库迁移）`，约 `:1637`）**之前**。
- 数据层运行时连接用 `get_db()`（返回带 `row_factory = sqlite3.Row` 的连接）。
- 成功响应 `{'success': True, ...}`；错误 `{'success': False, 'error': '...'}` + HTTP 状态码。
- 密码**明文**存储：写入与读取都**不**调用 `encrypt_data`/`decrypt_data`。

---

## 任务 1：新增数据表 `outlook_upload_accounts`

**文件：**
- 修改：`outlook_web/segments/01_bootstrap.py`（`init_db()` 内，迁移段之前）
- 测试：`tests/test_outlook_upload_accounts.py`

- [ ] **步骤 1：编写失败的测试**

创建 `tests/test_outlook_upload_accounts.py`，内容如下（本任务先建表测试，后续任务在同文件追加类）：

```python
import importlib
import os
import tempfile
import unittest


os.environ.setdefault('SECRET_KEY', 'test-secret-key')
if 'DATABASE_PATH' not in os.environ:
    _temp_dir = tempfile.mkdtemp(prefix='outlookEmail-upload-tests-')
    os.environ['DATABASE_PATH'] = os.path.join(_temp_dir, 'test.db')

web_outlook_app = importlib.import_module('web_outlook_app')


class OutlookUploadSchemaTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()

    def test_table_exists_with_expected_columns_and_defaults(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            columns = {row[1]: row for row in db.execute(
                'PRAGMA table_info(outlook_upload_accounts)'
            ).fetchall()}

        for name in ['id', 'email', 'password', 'is_authorized',
                     'status', 'remark', 'source', 'created_at', 'updated_at']:
            self.assertIn(name, columns)

    def test_is_authorized_defaults_to_zero(self):
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                ('default@outlook.com', 'pwd'),
            )
            db.commit()
            row = db.execute(
                "SELECT is_authorized, status, source FROM outlook_upload_accounts WHERE email = ?",
                ('default@outlook.com',),
            ).fetchone()

        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['source'], 'external_api')

    def test_email_is_unique(self):
        import sqlite3
        with self.app.app_context():
            db = web_outlook_app.get_db()
            db.execute(
                "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                ('dup@outlook.com', 'p1'),
            )
            db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO outlook_upload_accounts (email, password) VALUES (?, ?)",
                    ('dup@outlook.com', 'p2'),
                )
                db.commit()


if __name__ == '__main__':
    unittest.main()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadSchemaTests -v`
预期：FAIL，报错 `sqlite3.OperationalError: no such table: outlook_upload_accounts`

- [ ] **步骤 3：编写最少实现代码**

在 `outlook_web/segments/01_bootstrap.py` 的 `init_db()` 内、迁移段注释 `# 检查并添加缺失的列（数据库迁移）`（约 `:1637`）**之前**，加入建表与索引语句（`cursor` 是 `init_db()` 内已有的游标变量）：

```python
    # 外部上传的 Outlook 账号暂存表（账号/密码/是否授权，独立于 accounts）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS outlook_upload_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_authorized INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            remark TEXT DEFAULT '',
            source TEXT DEFAULT 'external_api',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_outlook_upload_email
        ON outlook_upload_accounts(email)
    ''')
```

> 实现提示：先用 Grep 在 `01_bootstrap.py` 搜索精确字符串 `# 检查并添加缺失的列` 确认插入行号；确认 `init_db()` 内游标变量名为 `cursor`（若不同则改用实际变量名）。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadSchemaTests -v`
预期：PASS（3 个测试全通过）

- [ ] **步骤 5：Commit**

```bash
git add outlook_web/segments/01_bootstrap.py tests/test_outlook_upload_accounts.py
git commit -m "feat: 新增 outlook_upload_accounts 上传暂存表"
```

---

## 任务 2：数据层函数 `add_upload_account` / `add_upload_accounts_bulk`

**文件：**
- 修改：`outlook_web/segments/02_groups_accounts.py`（与现有账号读写函数同区域，例如紧跟 `add_accounts_bulk` 之后）
- 测试：`tests/test_outlook_upload_accounts.py`（追加新类）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_outlook_upload_accounts.py` 的 `if __name__ == '__main__':` 之前追加：

```python
class OutlookUploadDataLayerTests(unittest.TestCase):
    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()

    def test_add_single_account_normalizes_and_persists_plaintext(self):
        with self.app.app_context():
            result = web_outlook_app.add_upload_account('  USER@Outlook.com ', 'secret', 'note')
            web_outlook_app.get_db().commit()
            self.assertEqual(result['status'], 'added')
            self.assertEqual(result['email'], 'user@outlook.com')
            self.assertIsInstance(result['id'], int)

            row = web_outlook_app.get_db().execute(
                "SELECT email, password, is_authorized, remark FROM outlook_upload_accounts WHERE id = ?",
                (result['id'],),
            ).fetchone()
        self.assertEqual(row['email'], 'user@outlook.com')
        self.assertEqual(row['password'], 'secret')   # 明文，未加密
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['remark'], 'note')

    def test_add_duplicate_email_returns_duplicate(self):
        with self.app.app_context():
            web_outlook_app.add_upload_account('dupe@outlook.com', 'p1')
            web_outlook_app.get_db().commit()
            result = web_outlook_app.add_upload_account('dupe@outlook.com', 'p2')
            web_outlook_app.get_db().commit()
            self.assertEqual(result['status'], 'duplicate')
            row = web_outlook_app.get_db().execute(
                "SELECT password FROM outlook_upload_accounts WHERE email = ?",
                ('dupe@outlook.com',),
            ).fetchone()
        self.assertEqual(row['password'], 'p1')   # 原值未被覆盖

    def test_add_invalid_email_or_empty_password_returns_invalid(self):
        with self.app.app_context():
            r1 = web_outlook_app.add_upload_account('not-an-email', 'p')
            r2 = web_outlook_app.add_upload_account('ok@outlook.com', '')
            web_outlook_app.get_db().commit()
        self.assertEqual(r1['status'], 'invalid')
        self.assertEqual(r2['status'], 'invalid')

    def test_bulk_add_reports_counts_and_preserves_order(self):
        with self.app.app_context():
            web_outlook_app.add_upload_account('exists@outlook.com', 'old')
            web_outlook_app.get_db().commit()
            summary = web_outlook_app.add_upload_accounts_bulk([
                {'email': 'new1@outlook.com', 'password': 'p1'},
                {'email': 'exists@outlook.com', 'password': 'p2'},
                {'email': 'bad', 'password': 'p3'},
            ])
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['added'], 1)
        self.assertEqual(summary['duplicate'], 1)
        self.assertEqual(summary['invalid'], 1)
        self.assertEqual([r['status'] for r in summary['results']],
                         ['added', 'duplicate', 'invalid'])
        self.assertEqual([r['email'] for r in summary['results']],
                         ['new1@outlook.com', 'exists@outlook.com', 'bad'])
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadDataLayerTests -v`
预期：FAIL，报错 `AttributeError: module 'web_outlook_app' has no attribute 'add_upload_account'`

- [ ] **步骤 3：编写最少实现代码**

在 `outlook_web/segments/02_groups_accounts.py` 中（建议紧跟 `add_accounts_bulk` 函数之后）加入：

```python
def normalize_upload_email(email: str) -> str:
    return (email or '').strip().lower()


def add_upload_account(email: str, password: str, remark: str = '') -> Dict[str, Any]:
    """插入一条外部上传的 Outlook 账号。不在本函数内 commit，由调用方统一提交。

    返回 {'email', 'status': 'added'|'duplicate'|'invalid', 'id'?}
    """
    normalized_email = normalize_upload_email(email)
    raw_password = password if password is not None else ''
    if '@' not in normalized_email or not raw_password:
        return {'email': normalized_email or (email or ''), 'status': 'invalid'}

    db = get_db()
    cursor = db.execute(
        '''
        INSERT OR IGNORE INTO outlook_upload_accounts (email, password, remark, source)
        VALUES (?, ?, ?, 'external_api')
        ''',
        (normalized_email, raw_password, remark or ''),
    )
    if cursor.rowcount == 1:
        return {'email': normalized_email, 'status': 'added', 'id': cursor.lastrowid}
    return {'email': normalized_email, 'status': 'duplicate'}


def add_upload_accounts_bulk(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """单事务批量插入。items: [{'email','password','remark'?}, ...]"""
    results: List[Dict[str, Any]] = []
    added = duplicate = invalid = 0
    db = get_db()
    for item in items:
        outcome = add_upload_account(
            item.get('email', ''),
            item.get('password', ''),
            item.get('remark', ''),
        )
        if outcome['status'] == 'added':
            added += 1
        elif outcome['status'] == 'duplicate':
            duplicate += 1
        else:
            invalid += 1
        results.append(outcome)
    db.commit()
    return {
        'total': len(items),
        'added': added,
        'duplicate': duplicate,
        'invalid': invalid,
        'results': results,
    }
```

> 实现提示：确认 `02_groups_accounts.py` 顶部的类型导入已含 `Dict`, `Any`, `List`（现有 `add_accounts_bulk` 等已使用，应已具备）。`get_db` 在全局命名空间可直接用。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadDataLayerTests -v`
预期：PASS（4 个测试全通过）

- [ ] **步骤 5：Commit**

```bash
git add outlook_web/segments/02_groups_accounts.py tests/test_outlook_upload_accounts.py
git commit -m "feat: 上传账号数据层函数(单条/批量插入,明文存储)"
```

---

## 任务 3：外部上传路由 `POST /api/external/outlook/upload`

**文件：**
- 修改：`outlook_web/segments/07_routes_oauth_settings_external.py`（与 `/api/external/emails` 同文件）
- 测试：`tests/test_outlook_upload_accounts.py`（追加新类）

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_outlook_upload_accounts.py` 的 `if __name__ == '__main__':` 之前追加：

```python
class OutlookUploadRouteTests(unittest.TestCase):
    API_KEY = 'test-external-key'

    def setUp(self):
        self.app = web_outlook_app.app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            web_outlook_app.init_db()
            db = web_outlook_app.get_db()
            db.execute('DELETE FROM outlook_upload_accounts')
            db.commit()
            self.assertTrue(web_outlook_app.set_setting('external_api_key', self.API_KEY))

    def _headers(self):
        return {'X-API-Key': self.API_KEY}

    def test_requires_api_key(self):
        response = self.client.post('/api/external/outlook/upload',
                                    json={'email': 'a@outlook.com', 'password': 'p'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['success'])

    def test_single_upload_succeeds_and_hides_password(self):
        response = self.client.post(
            '/api/external/outlook/upload',
            headers=self._headers(),
            json={'email': 'single@outlook.com', 'password': 'secret', 'remark': 'n'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['added'], 1)
        self.assertEqual(payload['results'][0]['status'], 'added')
        # 响应不回显 password
        self.assertNotIn('password', payload['results'][0])
        self.assertNotIn('secret', response.get_data(as_text=True))

        with self.app.app_context():
            row = web_outlook_app.get_db().execute(
                "SELECT is_authorized, password FROM outlook_upload_accounts WHERE email = ?",
                ('single@outlook.com',),
            ).fetchone()
        self.assertEqual(row['is_authorized'], 0)
        self.assertEqual(row['password'], 'secret')

    def test_bulk_upload_reports_counts(self):
        response = self.client.post(
            '/api/external/outlook/upload',
            headers=self._headers(),
            json={'accounts': [
                {'email': 'b1@outlook.com', 'password': 'p1'},
                {'email': 'b1@outlook.com', 'password': 'p2'},
                {'email': 'bad', 'password': 'p3'},
            ]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['total'], 3)
        self.assertEqual(payload['added'], 1)
        self.assertEqual(payload['duplicate'], 1)
        self.assertEqual(payload['invalid'], 1)

    def test_empty_body_returns_400(self):
        response = self.client.post('/api/external/outlook/upload',
                                    headers=self._headers(), json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_route_is_marked_api_key_required(self):
        view = self.app.view_functions['api_external_upload_outlook']
        self.assertTrue(getattr(view, '_requires_api_key', False))
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadRouteTests -v`
预期：FAIL（`test_route_is_marked_api_key_required` 报 `KeyError: 'api_external_upload_outlook'`，上传相关用例返回 404）

- [ ] **步骤 3：编写最少实现代码**

在 `outlook_web/segments/07_routes_oauth_settings_external.py` 中（建议紧邻 `api_external_get_emails` 路由）加入：

```python
@app.route('/api/external/outlook/upload', methods=['POST'])
@csrf_exempt
@api_key_required
def api_external_upload_outlook():
    """对外 API：上传 Outlook 邮箱账号密码到上传表（默认未授权）。

    支持单条 {email, password, remark?} 或批量 {accounts: [...]}。
    """
    data = request.get_json(silent=True) or {}

    raw_accounts = data.get('accounts')
    if isinstance(raw_accounts, list) and raw_accounts:
        items = [
            {
                'email': item.get('email', ''),
                'password': item.get('password', ''),
                'remark': item.get('remark', ''),
            }
            for item in raw_accounts
            if isinstance(item, dict)
        ]
    elif data.get('email'):
        items = [{
            'email': data.get('email', ''),
            'password': data.get('password', ''),
            'remark': data.get('remark', ''),
        }]
    else:
        return jsonify({'success': False, 'error': '请求体需包含 email/password 或非空 accounts 数组'}), 400

    summary = add_upload_accounts_bulk(items)
    return jsonify({'success': True, **summary})
```

> 实现提示：`app`、`csrf_exempt`、`api_key_required`、`request`、`jsonify`、`add_upload_accounts_bulk` 均在全局命名空间，无需 import。参考同文件 `api_external_get_emails` 的装饰器顺序（`@app.route` → `@csrf_exempt` → `@api_key_required`）。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_outlook_upload_accounts.py::OutlookUploadRouteTests -v`
预期：PASS（5 个测试全通过）

- [ ] **步骤 5：运行整个测试文件 + 回归冒烟**

运行：`python -m pytest tests/test_outlook_upload_accounts.py tests/test_imap_folder_resolution.py -v`
预期：全部 PASS（确认未破坏现有外部接口测试）

- [ ] **步骤 6：Commit**

```bash
git add outlook_web/segments/07_routes_oauth_settings_external.py tests/test_outlook_upload_accounts.py
git commit -m "feat: 外部上传接口 POST /api/external/outlook/upload"
```

---

## 任务 4：更新 `docs/api.md`

**文件：**
- 修改：`docs/api.md`

- [ ] **步骤 1：在"对外 API"汇总表新增一行**

用 Grep 在 `docs/api.md` 搜索现有行 `/api/external/emails` 所在的汇总表（约 `:34-39`）。在该表中、`/api/external/emails` 行之后追加一行：

```markdown
| POST | `/api/external/outlook/upload` | API Key | JSON | 上传 Outlook 邮箱账号密码到上传表（默认未授权，支持单条/批量） |
```

> 实现提示：先 Read 该表确认列顺序与分隔格式（`方法 | 路径 | 鉴权 | 返回类型 | 说明`），逐列对齐后再插入。

- [ ] **步骤 2：在"对外 API"详情区新增小节**

用 Grep 找到详情区中 `### GET \`/api/external/emails\`` 小节的**结尾**（即下一个 `### ` 或 `## ` 标题之前）。在其后插入以下完整小节：

````markdown
### POST `/api/external/outlook/upload`

上传 Outlook 邮箱账号和密码，保存到独立的上传暂存表 `outlook_upload_accounts`。入库记录的"是否授权"字段默认值为未授权（`is_authorized = 0`）。支持一次上传单条或批量。

> 说明：该接口仅负责存储，不触发授权流程；上传的密码以明文存储于上传表。

#### 请求体

单条：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 是 | 邮箱账号，入库前转小写并去除首尾空格；重复将被跳过 |
| `password` | string | 是 | 邮箱密码 |
| `remark` | string | 否 | 备注 |

批量（与上面二选一）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `accounts` | array | 是 | 元素为 `{email, password, remark?}` 的数组；非空时按批量处理 |

#### 请求示例

```bash
# 单条
curl -X POST -H "X-API-Key: your-api-key" -H "Content-Type: application/json" \
  -d '{"email":"user@outlook.com","password":"pwd123","remark":"可选"}' \
  "http://localhost:5000/api/external/outlook/upload"

# 批量
curl -X POST -H "X-API-Key: your-api-key" -H "Content-Type: application/json" \
  -d '{"accounts":[{"email":"a@outlook.com","password":"p1"},{"email":"b@outlook.com","password":"p2"}]}' \
  "http://localhost:5000/api/external/outlook/upload"
```

#### 成功响应示例

```json
{
  "success": true,
  "total": 2,
  "added": 1,
  "duplicate": 1,
  "invalid": 0,
  "results": [
    { "email": "a@outlook.com", "status": "added", "id": 5 },
    { "email": "b@outlook.com", "status": "duplicate" }
  ]
}
```

#### 返回说明

- `total` / `added` / `duplicate` / `invalid`：本次处理总数与各状态计数
- `results[].status` 取值：
  - `added`：新增成功，附带 `id`
  - `duplicate`：`email` 已存在，被跳过（不覆盖原记录）
  - `invalid`：`email` 缺少 `@` 或 `password` 为空，未入库
- 响应不回显 `password`
- 入库记录 `is_authorized` 一律为 `0`（未授权）
- 请求体既无 `email` 也无非空 `accounts` 时返回 HTTP 400
- 缺少 / 无效 API Key 时由鉴权层返回 HTTP 401 / 403
````

- [ ] **步骤 3：人工核对文档渲染**

运行：`python -c "import pathlib; print('/api/external/outlook/upload' in pathlib.Path('docs/api.md').read_text(encoding='utf-8'))"`
预期：输出 `True`（确认内容已写入；Markdown 表格/代码块对齐靠肉眼复核）

- [ ] **步骤 4：Commit**

```bash
git add docs/api.md
git commit -m "docs: 补充外部上传接口 /api/external/outlook/upload 文档"
```

---

## 任务 5：全量回归与收尾

- [ ] **步骤 1：运行完整测试套件**

运行：`python -m pytest tests/ -v`
预期：全部 PASS（新增 `test_outlook_upload_accounts.py` 通过，且无既有测试回归）

- [ ] **步骤 2：确认无遗漏改动**

运行：`git status`
预期：工作区干净，无未跟踪/未提交的相关文件

---

## 自检结果

**1. 规格覆盖度：**
- 设计 §3 新表 → 任务 1 ✓
- 设计 §4 数据层函数 → 任务 2 ✓
- 设计 §5 外部上传接口（API Key、单条/批量、响应不回显 password、is_authorized=0、400/401/403）→ 任务 3 ✓
- 设计 §6 docs/api.md（汇总表行 + 详情小节）→ 任务 4 ✓
- 设计 §9 验证要点 → 分散在任务 1-3 的测试 + 任务 5 全量回归 ✓
- 设计 §2.2 不做项（不碰 accounts、不做授权动作、不做 multipart）→ 计划中无相关任务，符合 ✓

**2. 占位符扫描：** 无 TODO/待定；所有代码步骤均含完整代码与精确命令。

**3. 类型一致性：** `add_upload_account`（任务 2 定义）返回 `{'email','status','id'?}`，被任务 2 批量函数与任务 3 路由测试一致引用；`add_upload_accounts_bulk` 返回结构（`total/added/duplicate/invalid/results`）在任务 2、任务 3、任务 4 文档中一致；路由 view 名 `api_external_upload_outlook` 在任务 3 实现与测试中一致；表名/列名在任务 1-4 全程一致。
