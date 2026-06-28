# Graph refresh_token 自动提取功能迁移分析

## 结论

`reg-factory` Web 页面上的“提取 Graph refresh_token”不是独立业务页面，而是通用脚本运行器中的一个脚本入口。完整链路是：

`webui/scripts.py` 注册脚本 schema -> `webui/static/app.js` 自动渲染表单 -> `POST /api/run` 启动子进程 -> `GET /api/logs/{run_id}` SSE 推送日志 -> `extract_graph_tokens.py` 执行纯 HTTP Microsoft OAuth 授权码流程 -> 输出 `outlook_accounts/graph_tokens_*.txt`。

真正需要迁移的是 `extract_graph_tokens.py` 中“用邮箱密码模拟 Microsoft 登录并截获授权码，再换取 Graph refresh_token”的核心状态机。`reg-factory` 的 WebUI 脚本壳可以作为批量任务和日志流参考，但不建议原样搬到 `outlookEmail`，因为当前项目已经有 Flask segment、账号入库、token 刷新验证、SSE 日志等现成能力。

## reg-factory 实现链路

### 1. Web 页面入口

文件：`D:\IdeaSpace\GitSpace\reg-factory\webui\scripts.py`

脚本入口定义如下：

```python
{
    "id": "extract_graph_tokens",
    "file": "extract_graph_tokens.py",
    "category": "养号/邮箱",
    "title": "提取 Graph refresh_token",
    "desc": "用账号密码换 Microsoft Graph refresh_token(免浏览器)，输出到 outlook_accounts/。",
    "args": [
        {"flag": "accounts_file", "type": "str", "default": "", "positional": True},
        {"flag": "--email", "type": "str", "default": ""},
        {"flag": "--password", "type": "str", "default": ""},
        {"flag": "--concurrency", "type": "int", "default": 5},
    ],
}
```

这个 schema 只描述“页面上有哪些输入”和“最终执行哪个 Python 文件”。它不包含 OAuth 逻辑。

### 2. 前端表单和任务启动

文件：`D:\IdeaSpace\GitSpace\reg-factory\webui\static\app.js`

前端启动流程：

1. 页面加载时请求 `/api/scripts`，拿到 `scripts.py` 中的脚本 schema。
2. 根据 `category` 分组渲染左侧按钮。
3. 点击“提取 Graph refresh_token”后，`renderForm(s)` 根据 `args` 自动生成输入框。
4. 点击运行后，`collectArgs(s)` 收集表单值。
5. `runScript()` 向 `/api/run` 发送：

```json
{
  "script": "extract_graph_tokens",
  "args": {
    "accounts_file": "...",
    "--email": "...",
    "--password": "...",
    "--concurrency": 5
  }
}
```

6. 后端返回 `run_id` 后，前端打开 `EventSource('/api/logs/{run_id}')`，把子进程 stdout/stderr 逐行追加到日志面板。

### 3. 后端通用脚本执行器

文件：`D:\IdeaSpace\GitSpace\reg-factory\webui\server.py`

核心职责：

- `/api/scripts` 返回脚本 schema。
- `_build_cmd(script, args)` 把表单参数拼成命令行，例如：

```text
python -u extract_graph_tokens.py --email user@outlook.com --password xxx --concurrency 5
```

- `/api/run` 用 `asyncio.create_subprocess_exec()` 在 `reg-factory` 根目录启动子进程。
- 子进程输出被异步读取到内存 `RUNS[run_id]["lines"]`。
- `/api/logs/{run_id}` 用 SSE 持续推送日志，任务结束后发送 `done` 事件。

子进程环境由 `_child_env()` 注入：

- `PYTHONUNBUFFERED=1`：保证日志实时输出。
- `PYTHONIOENCODING=utf-8`：避免 Windows 中文输出乱码。
- 从 `.env` 的 `CLASH_PROXY` 注入 `HTTP_PROXY`、`HTTPS_PROXY`。
- `NO_PROXY=127.0.0.1,localhost,::1`：避免本地地址走代理。

### 4. 核心脚本

文件：`D:\IdeaSpace\GitSpace\reg-factory\extract_graph_tokens.py`

关键常量：

```python
CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"  # Thunderbird public client
REDIRECT_URI = "http://localhost"
SCOPE = "offline_access https://graph.microsoft.com/Mail.Read"
OUTPUT_DIR = "outlook_accounts"
```

注意：这里使用的是 Graph `Mail.Read` scope，不是 `https://outlook.office.com/IMAP.AccessAsUser.All`。`reg-factory` 下游用 Graph REST 读邮件，IMAP 资源域的 refresh_token 不能稳定换取 Graph access token。

## 纯 HTTP OAuth 状态机

核心函数：`get_graph_token(email, password, idx=0)`

### 1. 初始化 session

脚本使用 `requests.Session()`，设置：

- `session.trust_env = True`，继承环境代理。
- Chrome 风格 `User-Agent`。
- 所有主要网络请求 `timeout=30`。

### 2. 请求 Microsoft authorize 页面

请求地址：

```text
https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize
```

参数：

- `client_id=9e5f94bc-e8a4-4e73-b8be-63364c29d753`
- `response_type=code`
- `redirect_uri=http://localhost`
- `scope=offline_access https://graph.microsoft.com/Mail.Read`
- `response_mode=query`

返回 HTML 后，脚本用正则提取 Microsoft 登录页的动态字段：

- `PPFT`：优先从 `sFTTag` 提取，失败后从 hidden input `name="PPFT"` 提取。
- `urlPost`：登录表单提交地址。
- `sCtx`：登录上下文。

如果没有拿到 `PPFT`，流程立即失败。

### 3. 提交账号密码

向 `urlPost` 发送表单字段，核心字段包括：

- `login`
- `loginfmt`
- `passwd`
- `PPFT`
- `ctx`
- `type=11`
- `LoginOptions=3`

这一步相当于模拟浏览器在 Microsoft 登录页提交账号密码。

### 4. 处理中间页面

Microsoft 登录流程会因为账号状态、首次授权、安全信息提示等进入不同页面。脚本用一个最多 15 步的循环处理这些状态。

已覆盖的主要分支：

- JS 自动提交表单：页面包含 `DoSubmit`、`fmHF`、`onload` 时，解析 form `action` 和 hidden inputs，再 POST。
- HTTP 301/302/303/307：手动跟随跳转，遇到 `localhost?code=...` 时停止，不真的访问本地服务。
- `Consent/Update`：从页面脚本里的 `ServerData = {...};` 提取 `client_id`、`scope`、`cscope`、`canary`，POST `ucaction=Yes` 接受授权。
- `proofs/Add`：Microsoft 要求添加安全信息时，解析 form 并提交 `action=Skip` 跳过。
- 通用 form fallback：解析页面第一个 form，带 hidden inputs 提交；如果 URL 或 action 包含 consent，则补 `ucaccept=Yes`。

关键点是 `REDIRECT_URI=http://localhost`。脚本不启动本地 HTTP 服务，而是在重定向 URL 中直接捕获：

```text
http://localhost?code=...
```

然后解析 query string 得到 `auth_code`。

如果跳到：

```text
http://localhost?error=...
```

则从 `error_description` 或 `error` 中提取失败原因并结束。

### 5. 授权码换 token

请求地址：

```text
https://login.microsoftonline.com/consumers/oauth2/v2.0/token
```

POST 表单：

```python
{
    "client_id": CLIENT_ID,
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPE,
}
```

如果响应包含 `access_token`，脚本取出 `refresh_token` 并返回：

```python
{
    "email": email,
    "password": password,
    "refresh_token": rt,
    "client_id": CLIENT_ID,
}
```

## 输入、并发和输出

脚本支持三种输入模式：

1. 单账号：`--email` + `--password`。
2. 文件：位置参数 `accounts_file`，每行至少 `email----password`，后续字段忽略。
3. 自动扫描：不传参数时扫描 `unlock_results/unlocked_clean_*.txt`，并跳过 `outlook_accounts/graph_tokens_*.txt` 中已经提取过的邮箱。

批量处理使用：

```python
ThreadPoolExecutor(max_workers=args.concurrency)
```

默认并发数是 5。

输出文件：

```text
outlook_accounts/graph_tokens_YYYYMMDD_HHMMSS.txt
```

输出行格式：

```text
email----password----refresh_token----client_id
```

## reg-factory 下游使用方式

文件：`D:\IdeaSpace\GitSpace\reg-factory\common\mailbox.py`

下游通过 refresh_token 再换 Graph access token，然后请求 Graph 邮件接口读取验证码邮件。关键约束：

- 默认 `client_id` 也是 Thunderbird public client。
- refresh token 请求使用 `grant_type=refresh_token`。
- 邮件读取走 `https://graph.microsoft.com/...`，包括 inbox 和 junkemail。
- 因此提取阶段必须拿 Graph 资源域的 token。

## outlookEmail 当前相关能力

当前项目不是 Vue/FastAPI 结构，而是 Flask 单体应用 + segment 装配 + 静态 JS。

### 1. 应用装配

文件：`web_outlook_app.py`

`SEGMENT_FILES` 固定加载：

```python
(
    "01_bootstrap.py",
    "02_groups_accounts.py",
    "03_mail_helpers.py",
    "04_routes_groups_accounts.py",
    "05_routes_refresh_mail.py",
    "06_routes_temp_email.py",
    "07_routes_oauth_settings_external.py",
    "08_forwarding_scheduler_errors.py",
    "09_routes_system_update.py",
    "10_routes_email_shares.py",
)
```

如果新增 segment，需要同时更新这个列表。

### 2. 当前手动 OAuth 授权

后端：

- `outlook_web/segments/01_bootstrap.py`
  - `OAUTH_CLIENT_ID`
  - `OAUTH_REDIRECT_URI`
  - `OAUTH_SCOPES`
- `outlook_web/segments/07_routes_oauth_settings_external.py`
  - `GET /api/oauth/auth-url`
  - `POST /api/oauth/exchange-token`
  - `POST /api/accounts/<account_id>/reauthorize`

前端：

- `templates/partials/index/layout.html`：已有“授权并保存 Outlook 账号”入口。
- `templates/partials/index/dialogs-oauth.html`：手动 OAuth 弹窗。
- `static/js/index/06-utils-oauth.js`
  - `showGetRefreshTokenModal()`
  - `exchangeToken()`
  - `saveTokenAccount()`
  - `reauthorizeExistingAccount()`

当前手动 OAuth 使用：

- authorize/token endpoint：`https://login.microsoftonline.com/common/oauth2/v2.0/...`
- 默认 `OAUTH_CLIENT_ID=6daa9f56-5e67-4cb6-ae52-ef89ef912d36`
- 默认 `OAUTH_REDIRECT_URI=http://localhost:8080`
- scopes 包含 `Mail.Read`、`Mail.ReadWrite`、`User.Read`

这与 `reg-factory` 自动提取使用的 `consumers` endpoint、Thunderbird client id、`http://localhost` redirect URI 不完全一致。迁移时建议保留一组“自动提取专用常量”，不要直接改全局 `OAUTH_*`，以降低对现有手动授权和刷新逻辑的影响。

### 3. 账号持久化

数据库表和加密：

- `outlook_web/segments/01_bootstrap.py`：`accounts` 表包含 `email`、加密 `password`、`client_id`、加密 `refresh_token`、分组、状态、代理等字段。
- `encrypt_data()`、`decrypt_data()` 已存在。

账号导入：

- `outlook_web/segments/02_groups_accounts.py`
  - `ACCOUNT_INSERT_SQL`
  - `build_account_insert_values()`
  - `add_account()`
  - `add_accounts_bulk()`
  - `parse_outlook_account_string()`
  - `parse_account_import()`

当前导出常用格式是：

```text
email----password----client_id----refresh_token
```

但导入解析已经能通过 UUID 形态识别 `client_id`，可兼容 `reg-factory` 输出的：

```text
email----password----refresh_token----client_id
```

### 4. token 刷新和 Graph 读信

文件：`outlook_web/segments/03_mail_helpers.py`

已有能力：

- `request_graph_token_response()`：用 refresh_token 换 Graph token。
- `get_access_token_graph_result()`：Graph token 获取封装。
- `get_emails_graph()`：Graph API 获取邮件列表。
- 代理故障切换：`request_with_proxy_failover()`、`post_with_proxy_fallback()`。

文件：`outlook_web/segments/05_routes_refresh_mail.py`

已有能力：

- `test_refresh_token()`：验证 refresh token，优先 Graph，失败再 fallback。
- `refresh_outlook_account_token()`：读取账号、解密 refresh_token、按账号代理刷新并持久化 rotated refresh_token。
- `/api/accounts/refresh-selected-stream`：已有 SSE 任务模式，可作为批量提取日志流参考。

### 5. 外部上传账号暂存表

文件：`outlook_web/segments/01_bootstrap.py`

已有 `outlook_upload_accounts`：

- `email`
- 明文 `password`
- `is_authorized`
- `status`
- `remark`
- `source`

文件：`outlook_web/segments/07_routes_oauth_settings_external.py`

已有：

- `/api/external/outlook/upload`
- `/api/outlook-upload-accounts`

这张表可以作为批量自动提取的账号来源之一：从暂存表取未授权账号，提取成功后写入正式 `accounts` 表，并把暂存记录标记为已授权。

## 推荐迁移设计

### 1. 后端核心服务

建议把 `reg-factory` 的核心逻辑拆成纯函数或小服务，不要保留命令行脚本作为主集成方式。

推荐位置：

- 方案 A：新增模块 `outlook_web/graph_token_extractor.py`，由 segment 调用。
- 方案 B：新增 segment `11_routes_graph_token_extraction.py`，并在 `web_outlook_app.py` 的 `SEGMENT_FILES` 里追加。
- 方案 C：小范围实现时，直接放入 `07_routes_oauth_settings_external.py`，但文件会继续膨胀，不适合后续维护。

推荐核心函数签名：

```python
def extract_graph_refresh_token(
    email: str,
    password: str,
    *,
    client_id: str = GRAPH_EXTRACT_CLIENT_ID,
    redirect_uri: str = GRAPH_EXTRACT_REDIRECT_URI,
    scope: str = GRAPH_EXTRACT_SCOPE,
    log: Optional[Callable[[str], None]] = None,
    session_factory: Optional[Callable[[], requests.Session]] = None,
) -> Dict[str, Any]:
    ...
```

专用常量建议：

```python
GRAPH_EXTRACT_CLIENT_ID = os.getenv(
    "GRAPH_EXTRACT_CLIENT_ID",
    "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
)
GRAPH_EXTRACT_REDIRECT_URI = os.getenv("GRAPH_EXTRACT_REDIRECT_URI", "http://localhost")
GRAPH_EXTRACT_SCOPE = os.getenv(
    "GRAPH_EXTRACT_SCOPE",
    "offline_access https://graph.microsoft.com/Mail.Read",
)
GRAPH_EXTRACT_AUTHORITY = os.getenv("GRAPH_EXTRACT_AUTHORITY", "consumers")
```

### 2. API 设计

单账号：

```text
POST /api/oauth/graph-token/extract
```

请求：

```json
{
  "email": "user@outlook.com",
  "password": "password",
  "save": true,
  "group_id": 1,
  "remark": "auto extracted"
}
```

响应：

```json
{
  "success": true,
  "email": "user@outlook.com",
  "client_id": "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
  "refresh_token": "...",
  "saved": true
}
```

批量：

```text
POST /api/oauth/graph-token/extract-batch
GET  /api/oauth/graph-token/extract-batch/<task_id>
```

`POST` 创建内存任务并立即返回 `task_id`；`GET` 用 SSE 推送进度、脱敏日志和最终统计。实现方式可参考 `refresh-selected-stream` 的任务表和 EventSource 前端逻辑。

批量来源可支持：

- 粘贴文本，每行 `email----password`。
- 上传文件解析后的文本。
- `outlook_upload_accounts` 中未授权账号 ID 列表。

### 3. 入库和验证

提取成功后不建议手写 SQL，优先复用现有账号导入能力：

- 构造 `email----password----refresh_token----client_id` 行，走现有解析和 `add_accounts_bulk()`。
- 或直接构造 parsed account dict，调用 `add_accounts_bulk()`。

如果是重新授权已有账号：

- 更新账号的 `refresh_token` 和 `client_id`。
- 调用现有 `refresh_outlook_account_token()` 或 `test_refresh_token()` 做一次 Graph 验证。
- 如果 token 响应返回 rotated refresh_token，沿用现有逻辑持久化新 token。

如果来源是 `outlook_upload_accounts`：

- 提取成功并写入 `accounts` 后，将对应暂存记录 `is_authorized=1`。
- 失败时只记录脱敏错误原因，不要把密码或 refresh_token 写入日志。

### 4. 前端集成

轻量方案：

- 在现有“授权并保存 Outlook 账号”弹窗中增加“账号密码提取”模式。
- 单账号输入邮箱、密码、分组、备注，提交到 `POST /api/oauth/graph-token/extract`。

批量方案：

- 在账号工具栏新增“批量提取 Graph token”入口。
- 支持粘贴多行账号或选择外部上传暂存账号。
- 使用 EventSource 展示进度日志和成功/失败统计。
- 成功结果可以直接入库，也可以提供兼容导出文本。

前端文件位置：

- `templates/partials/index/dialogs-oauth.html`：弹窗结构。
- `templates/partials/index/layout.html`：入口按钮。
- `static/js/index/06-utils-oauth.js`：单账号 OAuth 相关逻辑。
- `static/js/index/08-refresh.js`：可参考 SSE 任务和日志 UI。

### 5. 不建议新增的内容

除非明确需要审计历史，不建议第一版新增 `token_extraction_jobs`、`token_extraction_results` 等持久化表。当前需求可以用：

- 内存任务状态。
- SSE 日志。
- 正式 `accounts` 表。
- 可选的 `outlook_upload_accounts` 状态字段。

这样迁移成本更低，也更贴合当前项目结构。

## 关键兼容性注意事项

- `client_id`：`reg-factory` 使用 Thunderbird public client `9e5f94bc-e8a4-4e73-b8be-63364c29d753`。
- `redirect_uri`：必须与 client 允许的 redirect URI 匹配，`reg-factory` 使用 `http://localhost`。
- `scope`：保持 `offline_access https://graph.microsoft.com/Mail.Read`，否则后续 Graph 读信可能失败。
- authority：`reg-factory` 使用 `consumers`，当前手动 OAuth 使用 `common`。自动提取个人 Outlook 账号时优先沿用 `consumers`。
- 输出顺序：`reg-factory` 是 `email----password----refresh_token----client_id`，当前项目导出常用 `email----password----client_id----refresh_token`，迁移时要复用已有自动识别逻辑或显式指定格式。
- 代理：自动提取依赖 `requests.Session.trust_env=True` 和环境代理。迁移后应复用当前项目代理配置，至少支持全局代理和账号代理两种策略中的一种。
- 日志：不要输出完整密码、完整 refresh_token、完整授权 URL query。
- 并发：默认 5 对 Microsoft 登录流程偏激进。迁移到 Web 后建议提供并发配置，但默认从 1 或 2 开始，并加入失败退避。

## 测试建议

单元测试优先 mock `requests.Session`，不要在自动测试中真实登录 Microsoft。

建议覆盖：

- `PPFT` 从 `sFTTag` 提取。
- `PPFT` hidden input fallback。
- `urlPost`、`sCtx` 提取。
- JS 自动提交 form。
- `Consent/Update` 的 `ServerData` 解析和 `ucaction=Yes`。
- `proofs/Add` 的 `action=Skip`。
- `localhost?code=...` 授权码捕获。
- `localhost?error=...` 错误提取。
- token endpoint 成功和失败响应。
- `email----password----refresh_token----client_id` 能被当前导入解析接受。
- API 返回值和 SSE 日志不会泄漏密码、完整 token。

真实 Microsoft 账号的端到端测试应做成手动或 opt-in 测试，因为它依赖网络、代理、账号状态和 Microsoft 页面变化。

## 迁移检查清单

1. 新增自动提取专用常量，不改现有 `OAUTH_*` 默认值。
2. 把 `extract_graph_tokens.py` 状态机迁成可测试函数，移除直接 `print()`，改用 `log()` 回调。
3. 对日志做脱敏：邮箱可显示，密码不显示，refresh_token 只显示前后少量字符或不显示。
4. 增加单账号提取 API，并支持可选保存到 `accounts`。
5. 增加批量任务 API 和 SSE 流。
6. 复用 `add_accounts_bulk()` 入库，复用 `test_refresh_token()` 或 `refresh_outlook_account_token()` 验证。
7. 如接入 `outlook_upload_accounts`，成功后更新 `is_authorized`。
8. 前端先接单账号模式，再扩展批量模式。
9. 增加 mock 单元测试和导入解析测试。
10. 手动用一个真实测试账号验证：提取 -> 入库 -> Graph 刷新 -> 读取邮件。

## 最小可迁移范围

第一版可以只做：

- `outlook_web/graph_token_extractor.py`：核心提取函数。
- `outlook_web/segments/11_routes_graph_token_extraction.py`：单账号提取和批量 SSE 路由。
- 更新 `web_outlook_app.py`：追加新 segment。
- 更新 `templates/partials/index/dialogs-oauth.html` 和 `static/js/index/06-utils-oauth.js`：增加账号密码提取模式。
- 复用 `add_accounts_bulk()` 保存结果。

这样可以把功能闭环迁入当前项目，同时避免重建 `reg-factory` 的通用脚本运行器。
