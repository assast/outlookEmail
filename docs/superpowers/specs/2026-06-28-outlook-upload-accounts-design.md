# Outlook 邮箱上传存储表与外部上传接口 设计文档

- 日期：2026-06-28
- 状态：已确认设计，待编写实现计划

## 1. 背景与目标

系统现有 `accounts` 表统一存储 Outlook（OAuth）与 IMAP 账号，Outlook 账号依赖 `client_id` / `refresh_token`，且**没有显式的"是否授权"字段**——授权状态只能从 `refresh_token` 是否为空、`last_refresh_status` 间接推断。

本次需求：

1. 新建一张**独立**的表，专门存放从外部上传的 Outlook 账号，包含**账号、密码、是否授权**等字段，是否授权默认显示**未授权**。
2. 新增一个**外部可访问**的上传接口，可上传邮箱账号和密码，保存到这张新表。
3. 将接口写入 `docs/api.md`。

设计目标：职责单一、边界清晰，**不影响**现有 `accounts` 表及其列表/查询逻辑。该新表作为一个独立的"上传/待处理暂存区"。

## 2. 范围

### 2.1 包含

- 新表 `outlook_upload_accounts`（建表 + 索引）。
- 数据层函数：单条插入、批量插入。
- 外部上传接口 `POST /api/external/outlook/upload`（API Key 鉴权，支持单条与批量）。
- `docs/api.md` 文档更新。

### 2.2 不包含（YAGNI）

- 不修改 `accounts` 表，不改动现有列表/查询/展示逻辑。
- 不实现"授权"动作本身。本次只负责"存储为未授权"；如何把数据转入 `accounts`、如何触发 OAuth 授权，留待后续阶段，不在本设计内。
- 不实现 multipart / 文件上传（全项目无先例），仅接受 JSON 请求体。
- 不提供该表的查询 / 修改 / 删除接口（如后续需要再单独设计）。

## 3. 数据模型

### 3.1 新表 `outlook_upload_accounts`

建表语句放在 `outlook_web/segments/01_bootstrap.py` 的 `init_db()` 中，与其它 `CREATE TABLE IF NOT EXISTS` 并列，置于数据库迁移段（`# 检查并添加缺失的列`，约 `:1637`）**之前**。

```sql
CREATE TABLE IF NOT EXISTS outlook_upload_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,           -- 账号（唯一，去重依据，存小写去空格后的值）
    password TEXT NOT NULL,               -- 密码（明文存储，不加密）
    is_authorized INTEGER DEFAULT 0,      -- 是否授权：0=未授权（默认），1=已授权
    status TEXT DEFAULT 'active',         -- 记录状态，沿用现有约定
    remark TEXT DEFAULT '',               -- 备注（可选）
    source TEXT DEFAULT 'external_api',   -- 来源标记，便于区分上传渠道
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

配套索引（与其它 `CREATE INDEX IF NOT EXISTS` 并列）：

```sql
CREATE INDEX IF NOT EXISTS idx_outlook_upload_email ON outlook_upload_accounts(email);
```

### 3.2 字段说明

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER PK | 自增 | 主键 |
| `email` | TEXT | — | 账号，`UNIQUE NOT NULL`，入库前转小写并去除首尾空格 |
| `password` | TEXT | — | 密码，**明文存储**（按需求确认，不调用 `encrypt_data`） |
| `is_authorized` | INTEGER | `0` | 是否授权，默认 `0`（未授权） |
| `status` | TEXT | `'active'` | 记录状态，与现有表约定一致 |
| `remark` | TEXT | `''` | 备注，可选 |
| `source` | TEXT | `'external_api'` | 来源标记 |
| `created_at` | TIMESTAMP | `CURRENT_TIMESTAMP` | 创建时间 |
| `updated_at` | TIMESTAMP | `CURRENT_TIMESTAMP` | 更新时间 |

> 安全说明：`password` 明文存储是按用户明确要求确定的。现有 `accounts.password` 为加密存储；此处刻意不同。能读到该表 / 数据库文件者即可直接获得明文密码——这是已知且被接受的取舍。

## 4. 数据层函数

放在 `outlook_web/segments/02_groups_accounts.py`（与现有账号读写函数同文件）。

### 4.1 `add_upload_account(email, password, remark='') -> dict`

- 归一化：`email` 去首尾空格并转小写。
- 校验：`email` 非空且含 `@`；`password` 非空。校验失败返回 `{'email': <原值>, 'status': 'invalid'}`。
- 插入：`INSERT OR IGNORE INTO outlook_upload_accounts (email, password, remark, source)`，`is_authorized` 走默认 `0`，`source='external_api'`。
- 结果判定：
  - 新插入（`cursor.rowcount == 1`）→ `{'email', 'status': 'added', 'id': cursor.lastrowid}`
  - 因 `email` 已存在被忽略（`rowcount == 0`）→ `{'email', 'status': 'duplicate'}`
- 注意：函数本身**不** `commit`，由调用方（批量函数或路由）统一 `commit`，以便批量在单事务内完成。

### 4.2 `add_upload_accounts_bulk(items) -> dict`

- `items`：`[{'email','password','remark'?}, ...]`。
- 单事务内循环调用单条逻辑，累计统计；末尾 `db.commit()`。
- 返回：
  ```python
  {
    'total': len(items),
    'added': <int>,
    'duplicate': <int>,
    'invalid': <int>,
    'results': [ {'email','status','id'?}, ... ]   # 顺序与输入一致
  }
  ```

## 5. 外部上传接口

### 5.1 路由

```
POST /api/external/outlook/upload
```

位置：`outlook_web/segments/07_routes_oauth_settings_external.py`（与现有 `/api/external/emails` 同文件）。

装饰器（与现有 `/api/external/*` 完全一致）：

```python
@app.route('/api/external/outlook/upload', methods=['POST'])
@csrf_exempt
@api_key_required
def api_external_upload_outlook():
    ...
```

`@csrf_exempt` 必需（应用级开启了 CSRF）；`@api_key_required` 通过请求头 `X-API-Key` 或查询参数 `api_key` / `apikey` 校验外部 API Key。

### 5.2 请求体（JSON，单条或批量二选一）

单条：

```json
{ "email": "user@outlook.com", "password": "pwd123", "remark": "可选备注" }
```

批量：

```json
{
  "accounts": [
    { "email": "a@outlook.com", "password": "p1" },
    { "email": "b@outlook.com", "password": "p2", "remark": "x" }
  ]
}
```

请求体解析规则：

- 用 `request.get_json(silent=True)` 读取。
- 若含 `accounts` 且为非空数组 → 批量模式，调用 `add_upload_accounts_bulk`。
- 否则按单条解析（取顶层 `email`/`password`/`remark`），包成 `[item]` 后同样走批量函数（统一返回结构）。
- 请求体为空 / 既无 `accounts` 也无顶层 `email` → 返回 400。

### 5.3 响应

成功（沿用 `{success, ...}` 约定，**不回显 password**，`is_authorized` 一律为 `0`）：

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

错误：

- 请求体缺失或无有效账号字段 → `{"success": false, "error": "..."}`，HTTP 400。
- 缺少 / 无效 API Key → 由 `@api_key_required` 返回 `{"success": false, "error": "..."}`，HTTP 401 / 403。

`results[].status` 取值：`added`（新增成功）、`duplicate`（email 已存在被跳过）、`invalid`（email/password 校验不通过）。

## 6. 文档更新（docs/api.md）

1. 在"对外 API"汇总表（约 `docs/api.md:36`）新增一行：

   | 方法 | 路径 | 鉴权 | 返回类型 | 说明 |
   | --- | --- | --- | --- | --- |
   | POST | `/api/external/outlook/upload` | API Key | JSON | 上传 Outlook 邮箱账号密码到上传表（默认未授权） |

2. 在"对外 API"详情区新增 `### POST /api/external/outlook/upload` 小节，按现有格式包含：
   - 简介
   - `#### 请求体`（字段表：`字段 | 类型 | 必填 | 说明`，含单条与批量两种形态）
   - `#### 请求示例`（`curl` 单条 + 批量）
   - `#### 成功响应示例`（JSON）
   - `#### 返回说明`（`results[].status` 含义、密码不回显、`is_authorized` 默认 0、明文存储说明）

## 7. 实现落点汇总

| 改动 | 文件 | 位置 |
| --- | --- | --- |
| 建表 + 索引 | `outlook_web/segments/01_bootstrap.py` | `init_db()` 内，迁移段（约 `:1637`）之前；索引与其它 `CREATE INDEX` 并列 |
| 数据层函数 | `outlook_web/segments/02_groups_accounts.py` | 与现有账号读写函数同区域 |
| 上传路由 | `outlook_web/segments/07_routes_oauth_settings_external.py` | 与 `/api/external/emails` 同文件 |
| 文档 | `docs/api.md` | 汇总表（约 `:36`）+ 对外 API 详情区 |

## 8. 复用的现有约定

- 单一 Flask `app`，路由用 `@app.route(...)`，返回 `jsonify(...)`（`01_bootstrap.py:55`）。
- `get_db()` 取连接、`db.execute(sql, params)` + `db.commit()`（`01_bootstrap.py:1094`）。
- 外部鉴权 `api_key_required` + `csrf_exempt`（`03_mail_helpers.py:2254`）。
- 响应约定：成功 `{"success": true, ...}`，错误 `{"success": false, "error": "..."}`。
- `INSERT OR IGNORE` + `email UNIQUE` 去重（与 `accounts` 的 `add_accounts_bulk` 思路一致）。

## 9. 验证要点（供实现/测试阶段）

- 建表后 `outlook_upload_accounts` 存在，`is_authorized` 默认 0。
- 单条上传：新增返回 `added` + `id`；重复 email 返回 `duplicate`；缺字段返回 400。
- 批量上传：统计 `total/added/duplicate/invalid` 正确，`results` 顺序与输入一致。
- 无 / 错误 API Key：401 / 403。
- 响应体不含 password。
- 入库密码为明文（与设计一致）。
