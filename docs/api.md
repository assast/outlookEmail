# API 文档

本文档基于当前代码实现整理，目标是让 AI Agent、脚本或外部系统可以直接对接完整 API，而不是只给人看的零散说明。

## AI 对接总览

- 基础地址：`http(s)://<host>:<port>`
- 所有路由都在 `/api/*`
- 接口分为两类：
  - 对外 API：`/api/external/*`，使用 API Key
  - 完整管理 API：其余 `/api/*`，先登录 Web，再带 Session Cookie
- 浏览器扩展可以使用 `POST /api/extension/login` 通过 Web 登录密码换取一次性跳转地址，再建立正常 Web Session
- 写操作默认使用 JSON 请求体，`Content-Type: application/json`
- 大多数接口返回 JSON；少数接口返回文件下载或 SSE 事件流

推荐对接顺序：

1. 登录 Web，保存 Session Cookie
2. 调 `GET /api/csrf-token` 获取 CSRF Token
3. 读接口直接调 `GET`
4. 写接口在请求头带 `X-CSRFToken`

## 接口目录

### 基础与鉴权

| 方法 | 路径 | 鉴权 | 返回类型 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/api/version-status` | Session | JSON | 当前版本与仓库版本状态 |
| GET | `/api/csrf-token` | Session | JSON | 获取当前登录会话对应的 CSRF Token |
| POST | `/api/extension/login` | Web 登录密码 | JSON | 浏览器扩展获取一次性登录跳转地址 |
| GET | `/extension-login/<token>` | 一次性 token | Redirect | 消费扩展登录 token，建立 Web Session 后跳转 |

### 对外 API

| 方法 | 路径 | 鉴权 | 返回类型 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/api/external/accounts` | API Key | JSON | 获取普通邮箱账号列表 |
| GET | `/api/external/emails` | API Key | JSON | 获取指定邮箱邮件列表 |

### 分组、账号、标签、项目

| 方法 | 路径 | 鉴权 | 返回类型 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/api/groups` | Session | JSON | 获取分组列表 |
| GET | `/api/groups/<group_id>` | Session | JSON | 获取单个分组 |
| POST | `/api/groups` | Session + CSRF | JSON | 创建分组 |
| PUT | `/api/groups/<group_id>` | Session + CSRF | JSON | 更新分组 |
| DELETE | `/api/groups/<group_id>` | Session + CSRF | JSON | 删除分组 |
| PUT | `/api/groups/reorder` | Session + CSRF | JSON | 调整分组顺序 |
| POST | `/api/export/verify` | Session + CSRF | JSON | 获取导出二次验证令牌 |
| GET | `/api/groups/<group_id>/export` | Session | `text/plain` 下载 | 导出单个分组账号 |
| GET | `/api/accounts/export` | Session | `text/plain` 下载 | 导出全部账号 |
| POST | `/api/accounts/export-selected` | Session + CSRF | `text/plain` 下载 | 导出选中分组或选中账号 |
| GET | `/api/accounts` | Session | JSON | 获取账号列表 |
| GET | `/api/accounts/search` | Session | JSON | 搜索账号 |
| GET | `/api/accounts/<account_id>` | Session | JSON | 获取单个账号，不返回账号密码和 IMAP 密码明文 |
| POST | `/api/accounts/<account_id>/secrets` | Session + CSRF | JSON | 二次验证后获取账号密码和 IMAP 密码 |
| POST | `/api/accounts` | Session + CSRF | JSON | 批量导入账号 |
| PUT | `/api/accounts/<account_id>` | Session + CSRF | JSON | 更新账号 |
| POST | `/api/accounts/<account_id>/reauthorize` | Session + CSRF | JSON | 重新授权已有 Outlook 账号并自动刷新验证 |
| DELETE | `/api/accounts/<account_id>` | Session + CSRF | JSON | 按 ID 删除账号 |
| DELETE | `/api/accounts/email/<email_addr>` | Session + CSRF | JSON | 按邮箱删除账号 |
| POST | `/api/accounts/batch-delete` | Session + CSRF | JSON | 批量删除账号 |
| GET | `/api/accounts/<account_id>/aliases` | Session | JSON | 获取账号别名 |
| PUT | `/api/accounts/<account_id>/aliases` | Session + CSRF | JSON | 整体替换账号别名 |
| POST | `/api/accounts/batch-update-group` | Session + CSRF | JSON | 批量改分组 |
| POST | `/api/accounts/batch-update-forwarding` | Session + CSRF | JSON | 批量改转发开关 |
| POST | `/api/accounts/batch-update-proxy` | Session + CSRF | JSON | 批量改账号级代理 |
| GET | `/api/tags` | Session | JSON | 获取标签列表 |
| POST | `/api/tags` | Session + CSRF | JSON | 创建标签 |
| DELETE | `/api/tags/<tag_id>` | Session + CSRF | JSON | 删除标签 |
| POST | `/api/accounts/tags` | Session + CSRF | JSON | 批量改账号标签 |
| GET | `/api/projects` | Session | JSON | 获取项目列表 |
| GET | `/api/projects/<project_key>` | Session | JSON | 获取项目详情 |
| POST | `/api/projects/start` | Session + CSRF | JSON | 创建或补全项目范围 |
| GET | `/api/projects/<project_key>/accounts` | Session | JSON | 获取项目账号列表 |
| POST | `/api/projects/<project_key>/claim-random` | Session + CSRF | JSON | 随机领取项目邮箱 |
| POST | `/api/projects/<project_key>/complete-success` | Session + CSRF | JSON | 标记项目邮箱成功 |
| POST | `/api/projects/<project_key>/complete-failed` | Session + CSRF | JSON | 标记项目邮箱失败 |
| POST | `/api/projects/<project_key>/release` | Session + CSRF | JSON | 释放领取中的项目邮箱 |
| POST | `/api/projects/<project_key>/reset-failed` | Session + CSRF | JSON | 把失败状态重置回可领取 |
| POST | `/api/projects/<project_key>/remove-account` | Session + CSRF | JSON | 从项目移出邮箱 |
| POST | `/api/projects/<project_key>/restore-account` | Session + CSRF | JSON | 恢复已移出的项目邮箱 |

### 刷新、日志、邮件、设置、临时邮箱

| 方法 | 路径 | 鉴权 | 返回类型 | 说明 |
| --- | --- | --- | --- | --- |
| POST | `/api/accounts/<account_id>/refresh` | Session + CSRF | JSON | 刷新单个 Outlook 账号 |
| POST | `/api/accounts/refresh-selected` | Session + CSRF | JSON | 刷新选中账号 |
| POST | `/api/accounts/refresh-selected-stream` | Session + CSRF | JSON | 初始化选中账号流式刷新任务 |
| GET | `/api/accounts/refresh-selected-stream/<task_id>` | Session | `text/event-stream` | 订阅选中账号流式刷新任务 |
| GET | `/api/accounts/refresh-all` | Session | `text/event-stream` | 全量刷新账号 |
| POST | `/api/accounts/<account_id>/retry-refresh` | Session + CSRF | JSON | 重试单个失败账号 |
| GET | `/api/accounts/refresh-failed-stream` | Session | `text/event-stream` | 流式重试失败账号 |
| POST | `/api/accounts/refresh-failed` | Session + CSRF | JSON | 批量重试失败账号 |
| GET | `/api/accounts/trigger-scheduled-refresh` | Session | `text/event-stream` | 手动触发一次定时刷新逻辑 |
| POST | `/api/accounts/stop-full-refresh` | Session + CSRF | JSON | 请求停止当前全量刷新 |
| GET | `/api/accounts/refresh-logs` | Session | JSON | 刷新日志列表 |
| GET | `/api/accounts/<account_id>/refresh-logs` | Session | JSON | 单账号刷新日志 |
| GET | `/api/accounts/refresh-logs/failed` | Session | JSON | 当前失败邮箱快照 |
| GET | `/api/accounts/refresh-stats` | Session | JSON | 刷新统计 |
| GET | `/api/accounts/refresh-status-list` | Session | JSON | Token 刷新管理页数据 |
| GET | `/api/accounts/forwarding-logs` | Session | JSON | 转发日志列表 |
| GET | `/api/accounts/forwarding-logs/failed` | Session | JSON | 最近失败转发记录 |
| GET | `/api/accounts/<account_id>/forwarding-logs` | Session | JSON | 单账号转发日志 |
| POST | `/api/accounts/trigger-forwarding-check` | Session + CSRF | JSON | 立即触发一次转发检查 |
| POST | `/api/accounts/<account_id>/forwarding/reset-cursor` | Session + CSRF | JSON | 重置单账号转发游标 |
| GET | `/api/emails/<email_addr>` | Session | JSON | 获取内部邮件列表 |
| POST | `/api/emails/mark-read` | Session + CSRF | JSON | 批量标记邮件为已读 |
| POST | `/api/emails/delete` | Session + CSRF | JSON | 批量删除邮件 |
| GET | `/api/email/<email_addr>/<message_id>` | Session | JSON | 获取邮件详情 |
| GET | `/api/email/<email_addr>/<message_id>/attachments/<attachment_id>` | Session | 文件流 | 下载附件 |
| GET | `/api/email/<email_addr>/<message_id>/attachments/download-all` | Session | ZIP 文件流 | 打包下载全部附件 |
| POST | `/api/emails/retain-bodies` | Session + CSRF | JSON | 为已保留普通邮箱列表行补齐正文缓存 |
| GET | `/api/settings/normal-mail-retention/status` | Session | JSON | 获取普通邮箱本地保留统计与清理状态 |
| POST | `/api/settings/normal-mail-retention/clear` | Session + CSRF | JSON | 启动普通邮箱本地保留缓存清理 |
| GET | `/api/temp-emails` | Session | JSON | 获取临时邮箱列表 |
| POST | `/api/temp-emails/import` | Session + CSRF | JSON | 批量导入临时邮箱 |
| POST | `/api/temp-emails/batch-delete` | Session + CSRF | JSON | 批量删除临时邮箱 |
| POST | `/api/temp-emails/tags` | Session + CSRF | JSON | 批量改临时邮箱标签 |
| GET | `/api/duckmail/domains` | Session | JSON | 获取 DuckMail 域名 |
| GET | `/api/cloudflare/channels` | Session | JSON | 获取 Cloudflare 渠道列表 |
| POST | `/api/cloudflare/channels` | Session + CSRF | JSON | 创建 Cloudflare 渠道 |
| PUT | `/api/cloudflare/channels/<id>` | Session + CSRF | JSON | 更新 Cloudflare 渠道 |
| DELETE | `/api/cloudflare/channels/<id>` | Session + CSRF | JSON | 删除未被临时邮箱引用的 Cloudflare 渠道 |
| GET | `/api/cloudflare/domains` | Session | JSON | 获取指定 Cloudflare 渠道域名 |
| POST | `/api/temp-emails/generate` | Session + CSRF | JSON | 生成临时邮箱 |
| POST | `/api/temp-emails/generate-batch` | Session + CSRF | JSON | 批量生成 Cloudflare 临时邮箱 |
| POST | `/api/cloudflare/ai-usernames/test` | Session + CSRF | JSON | 使用草稿配置测试 AI 用户名生成 |
| POST | `/api/cloudflare/ai-usernames/generate` | Session + CSRF | JSON | 使用已保存配置生成 Cloudflare 用户名列表 |
| DELETE | `/api/temp-emails/<email_addr>` | Session + CSRF | JSON | 删除临时邮箱 |
| GET | `/api/temp-emails/<email_addr>/messages` | Session | JSON | 获取临时邮箱邮件列表 |
| GET | `/api/temp-emails/<email_addr>/messages/<message_id>` | Session | JSON | 获取临时邮件详情 |
| DELETE | `/api/temp-emails/<email_addr>/messages/<message_id>` | Session + CSRF | JSON | 删除单封临时邮件，当前为关闭状态 |
| DELETE | `/api/temp-emails/<email_addr>/clear` | Session + CSRF | JSON | 清空临时邮箱，当前为关闭状态 |
| POST | `/api/temp-emails/<email_addr>/refresh` | Session + CSRF | JSON | 主动刷新临时邮箱邮件 |
| GET | `/api/oauth/auth-url` | Session | JSON | 生成 Microsoft OAuth 授权链接 |
| POST | `/api/oauth/exchange-token` | Session + CSRF | JSON | 用回调 URL 换 Refresh Token |
| POST | `/api/settings/validate-cron` | Session + CSRF | JSON | 校验 Cron 表达式 |
| GET | `/api/settings` | Session | JSON | 获取系统设置 |
| PUT | `/api/settings` | Session + CSRF | JSON | 更新系统设置 |
| POST | `/api/settings/test-forward-channel` | Session + CSRF | JSON | 直接测试转发渠道 |
| GET | `/api/skins` | Session | JSON | 获取系统级外观皮肤列表与当前皮肤 |
| POST | `/api/skins/<skin_id>/activate` | Session + CSRF | JSON | 启用指定皮肤 |
| POST | `/api/skins/upload` | Session + CSRF | JSON | 上传 zip 皮肤包 |
| POST | `/api/skins/git/install` | Session + CSRF | JSON | 从 Git 仓库安装皮肤 |
| POST | `/api/skins/<skin_id>/git/update` | Session + CSRF | JSON | 更新 Git 来源皮肤 |
| DELETE | `/api/skins/<skin_id>` | Session + CSRF | JSON | 删除未启用的自定义皮肤 |

## 认证

### 对外 API

对外 API 使用 API Key 认证，支持两种方式：

- Header: `X-API-Key: your-api-key`
- Query: `?api_key=your-api-key`

可在 Web 界面 `设置 -> 对外 API Key` 中配置。

### 完整 API

完整 API 需要先登录 Web 界面并携带 Session Cookie。

### 浏览器扩展密码登录

浏览器扩展不使用对外 API Key。扩展先调用 `POST /api/extension/login`，用 Web 登录密码换取 60 秒有效的一次性 `launch_url`；随后在浏览器标签页打开该 URL，服务端会在自身域名下写入正常 Web Session 并跳转到 Web 控制台。

请求体：

```json
{
  "password": "web-login-password",
  "next": "/#settings"
}
```

成功响应：

```json
{
  "success": true,
  "launch_url": "/extension-login/<token>?next=/%23settings",
  "expires_in": 60
}
```

说明：

- `next` 可选，必须是站内路径；非法值会回退到 `/`
- `launch_url` 只能消费一次，过期或重复打开会跳回登录页
- 扩展打开控制台后，后续 Web 页面仍按完整管理 API 的 Session + CSRF 规则工作

### CSRF

所有内部写操作默认都应带 `X-CSRFToken` 请求头，值来自 `GET /api/csrf-token`。

典型请求头：

```http
Content-Type: application/json
X-CSRFToken: <csrf-token>
Cookie: session=<session-cookie>
```

### 账号密码二次验证

`GET /api/accounts/<account_id>` 只返回 `has_password` 和 `has_imap_password` 标记，不返回账号密码或 IMAP 密码明文。需要展示密码时，调用 `POST /api/accounts/<account_id>/secrets` 并在 JSON 请求体中传入当前 Web 登录密码。`field` 可选值为 `password` 或 `imap_password`，用于只获取当前要展示的密码字段；不传 `field` 时兼容返回两个字段：

```json
{
  "password": "web-login-password",
  "field": "password"
}
```

验证成功后返回：

```json
{
  "success": true,
  "secrets": {
    "password": "account-password"
  }
}
```

更新账号时，如果请求体省略 `password` 或 `imap_password` 字段，后端会保留已有值；只有显式传入该字段时才会更新对应密码。

### 通用响应约定

绝大多数 JSON 接口都遵循下面的约定：

- `success=true` 表示本次调用整体成功
- `success=false` 表示调用失败，通常同时返回 `error` 或 `message`
- 部分接口会返回：
  - `partial=true`：部分成功
  - `details`：更细的失败原因
  - `total`、`count`、`items`：列表或统计数据
- 未捕获异常统一返回：
  - HTTP `500`
  - `{"success": false, "error": "<异常信息>"}`
- 邮件、IMAP、Graph 相关接口在失败时，`error` 有时不是字符串，而是结构化对象：

```json
{
  "code": "IMAP_CONNECT_FAILED",
  "message": "IMAP 连接失败",
  "type": "IMAPConnectError",
  "status": 502,
  "details": "",
  "trace_id": "..."
}
```

AI 客户端应优先判断 `success`，再兼容 `error` 既可能是字符串，也可能是对象。

### GET `/api/csrf-token`

获取当前登录会话可用的 CSRF Token。该接口要求已登录，并且返回值与当前 Session 绑定。

成功响应示例：

```json
{
  "csrf_token": "...",
  "csrf_disabled": false
}
```

若当前未启用 CSRF，会返回：

```json
{
  "csrf_token": null,
  "csrf_disabled": true
}
```

响应头会显式禁止缓存，并带 `Vary: Cookie`，AI 客户端不要跨会话复用这个 token。

### GET `/api/version-status`

获取当前运行版本与仓库最新版本的比较状态。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `refresh` | bool-like string | 否 | 传 `1`、`true`、`yes` 时强制刷新远程版本缓存 |

#### 成功响应示例

```json
{
  "success": true,
  "version_status": {
    "current_version": "v2.0.15",
    "latest_version": "v2.0.16",
    "latest_release_version": "v2.0.16",
    "latest_repository_version": "v2.0.16",
    "status": "update_available",
    "badge_label": "可更新",
    "hint": "发现新版本 v2.0.16",
    "source": "release",
    "update_url": "https://...",
    "release_url": "https://...",
    "repository_url": "https://...",
    "changelog_url": "https://...",
    "checked_at": "2026-05-01T05:00:00+00:00",
    "errors": []
  }
}
```

`version_status.status` 常见值：

- `update_available`
- `up_to_date`
- `ahead`
- `unknown`

## 邮箱别名说明

普通账号现在支持配置多个别名邮箱。

- 对外 API 和内部邮件接口传入主邮箱或别名邮箱都可以命中同一个账号
- 返回结果中可能包含：
  - `requested_email`: 请求里传入的邮箱
  - `resolved_email`: 实际命中的主邮箱
  - `matched_alias`: 若通过别名命中，则为对应别名；否则为空
- 别名邮箱支持常见特殊字符，例如 `+`、`@`、`&`
  - `@` 可以直接传
  - `+` 建议编码成 `%2B`
  - `&` 必须编码成 `%26`

典型用法：

1. 把外部邮箱 B 的邮件自动转发到本项目管理的邮箱 A
2. 在邮箱 A 下把邮箱 B 设置为别名
3. 后续直接通过本项目 API，用邮箱 B 作为 `email` 参数取邮件或取验证码

## 对外 API

### GET `/api/external/accounts`

获取当前系统中已管理的邮箱账号列表，适合外部系统先同步邮箱池，再按邮箱调用 `/api/external/emails` 取邮件。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `group_id` | int | 否 | 仅返回指定分组直属账号；不会递归包含子分组 |
| `limit` | int | 否 | 单页条数，最大 `10000`；不传时保持兼容，返回全部匹配账号 |
| `offset` | int | 否 | 分页偏移量，默认 `0` |
| `sort_by` | string | 否 | 排序字段，支持 `created_at`、`email`、`sort_order` |
| `sort_order` | string | 否 | 排序方向，`asc` 或 `desc`，默认 `desc` |
| `tag_ids` | string | 否 | 逗号分隔的标签 ID，仅返回包含任一标签的账号 |
| `include_untagged` | bool | 否 | 与 `tag_ids` 配合使用，是否包含未打标签账号 |

#### 请求示例

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/accounts"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/accounts?group_id=1"
```

#### 成功响应示例

```json
{
  "success": true,
  "total": 1,
  "accounts": [
    {
      "id": 1,
      "email": "user@outlook.com",
      "aliases": ["alias@example.com"],
      "alias_count": 1,
      "group_id": 1,
      "group_name": "默认分组",
      "group_color": "#666666",
      "remark": "主账号",
      "status": "active",
      "account_type": "outlook",
      "provider": "outlook",
      "forward_enabled": true,
      "last_refresh_at": "2026-04-09 14:20:00",
      "last_refresh_status": "success",
      "last_refresh_error": null,
      "created_at": "2026-04-09 14:00:00",
      "updated_at": "2026-04-09 14:20:00",
      "tags": [
        {
          "id": 1,
          "name": "核心",
          "color": "#1a1a1a"
        }
      ]
    }
  ]
}
```

#### 返回说明

- 该接口只返回普通邮箱账号，不包含临时邮箱列表
- 已隐藏密码、Refresh Token、IMAP 密码等敏感字段
- 如需拉取某个邮箱的邮件列表，再调用 `/api/external/emails`

### GET `/api/external/emails`

获取指定邮箱的邮件列表，支持主邮箱、别名邮箱、收件箱/垃圾箱聚合查询。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 是 | 主邮箱或别名邮箱；若包含 `+`，会先按完整地址匹配，未命中时再按本地部分从右到左逐级去掉 `+suffix` 回退匹配；若域名是 `gmail.com` 或 `googlemail.com`，原后缀候选都未命中后会回退到另一个后缀 |
| `folder` | string | 否 | `inbox`、`junkemail`、`deleteditems`、`all`。`all` 会同时抓取收件箱和垃圾邮件并按时间倒序合并 |
| `skip` | int | 否 | 分页偏移，默认 `0`；非数字使用默认值，负数按 `0` 处理。当 `folder=all` 时，对每个文件夹分别跳过 `skip` 封 |
| `top` | int | 否 | 返回数量，默认 `1`，最大 `50`；非数字使用默认值，负数按 `0` 处理。当 `folder=all` 时，表示每个文件夹各取 `top` 封 |
| `subject_contains` | string | 否 | 仅保留主题中包含该关键字的邮件 |
| `from_contains` | string | 否 | 仅保留发件人中包含该关键字的邮件 |
| `keyword` | string | 否 | 在主题、预览、正文中做进一步关键字过滤 |

#### 请求示例

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=alias@example.com&folder=all&top=10"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=alias@example.com&folder=all&top=10&subject_contains=verify&from_contains=github&keyword=reset"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user%2Balias%40example.com"
```

#### 成功响应示例

```json
{
  "success": true,
  "requested_email": "alias@example.com",
  "resolved_email": "user@outlook.com",
  "resolved_query_email": "alias@example.com",
  "fallback_used": false,
  "matched_alias": "alias@example.com",
  "method": "Graph API",
  "has_more": true,
  "emails": [
    {
      "id": "AAMk...",
      "subject": "Your verification code",
      "from": "no-reply@example.com",
      "date": "2026-04-09T14:20:00Z",
      "is_read": false,
      "has_attachments": false,
      "body_preview": "Your code is 123456",
      "folder": "inbox"
    }
  ]
}
```

#### 聚合模式说明

当 `folder=all` 时：

- 后端会同时抓取 `inbox` 和 `junkemail`
- `top` 是“每个文件夹各取多少封”
- 例如 `top=1` 时，最多返回 `收件箱 1 + 垃圾邮件 1 = 2` 封
- `skip` 也是“每个文件夹各跳过多少封”
- `top=0` 是合法的安全解析结果，会返回空列表而不是回退到默认数量
- 结果按标准化后的邮件时间统一倒序排序
- IMAP 场景会优先使用服务器返回的 `INTERNALDATE`；同时兼容 `Tue, 14 Apr 2026 08:20:50 +0000 (UTC)` 这类时间格式
- 每条邮件会带上 `folder`
- 若其中一个文件夹成功、另一个失败，会返回：
  - `success: true`
  - `partial: true`
  - `details` 中包含失败文件夹的错误信息

#### Gmail / Googlemail 后缀回退

当查询地址是 `@gmail.com` 或 `@googlemail.com` 时，账号解析会先按原地址和原后缀 plus-address 回退候选查找；都未命中后，再使用另一后缀重试。例如 `user+code@gmail.com` 的候选顺序是：

1. `user+code@gmail.com`
2. `user@gmail.com`
3. `user+code@googlemail.com`
4. `user@googlemail.com`

如果使用回退候选命中，响应会包含 `resolved_query_email`、`fallback_used`、`fallback_email` 等字段。

## 内部 API

## 分组管理

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/groups` | 无 | 获取所有分组，返回 `parent_id`、`level`、`account_count`、`descendant_account_count`、`sort_position` |
| GET | `/api/groups/<group_id>` | 路径参数 `group_id` | 获取单个分组详情 |
| POST | `/api/groups` | JSON: `name`、`description?`、`color?`、`proxy_url?`、`sort_position?`、`parent_id?` | 创建分组 |
| PUT | `/api/groups/<group_id>` | JSON: `name`、`description?`、`color?`、`proxy_url?`、`sort_position?`、`parent_id?` | 更新分组或移动父级 |
| DELETE | `/api/groups/<group_id>` | 路径参数 `group_id` | 删除分组；含子分组时级联删除子分组并把账号移回默认分组 |
| PUT | `/api/groups/reorder` | JSON: `group_ids: number[]`、`parent_id?` | 重新排序同一父级下的普通分组 |

创建或更新分组请求示例：

```json
{
  "name": "代理组",
  "description": "走香港代理",
  "color": "#1a1a1a",
  "proxy_url": "http://127.0.0.1:7890",
  "sort_position": 2,
  "parent_id": null
}
```

分组支持最多三级树形层级：

- `parent_id=null` 表示一级分组；指定一级分组为父级会创建二级分组，指定二级分组为父级会创建三级分组。
- 三级分组下不能再创建子分组；临时邮箱分组不能作为父分组，也不能被移动到其他分组下。
- `sort_position` 只在同一 `parent_id` 下生效，`PUT /api/groups/reorder` 也只重排同一父级的 `group_ids`。
- `account_count` 是当前分组直属账号数，`descendant_account_count` 是当前分组及所有后代分组账号数。
- 删除父分组会删除所有后代分组，并把被删除分组中的普通邮箱账号移动到默认分组。

## 导出与二次验证

导出接口都会先校验一次登录密码，拿到 `verify_token` 后再发起导出。`verify_token` 当前为一次性令牌，默认 5 分钟内有效。按分组导出时会包含该分组及所有子分组账号；同时传入父子分组时，账号只会导出一次。

| 方法 | 路径 | 参数 | 返回 |
| --- | --- | --- | --- |
| POST | `/api/export/verify` | JSON: `password` | JSON，返回 `verify_token` |
| GET | `/api/groups/<group_id>/export` | Query: `verify_token` | `text/plain` 文件下载 |
| GET | `/api/accounts/export` | Query: `verify_token` | `text/plain` 文件下载 |
| POST | `/api/accounts/export-selected` | JSON: `group_ids: number[]` 或 `account_ids: number[]`、`verify_token` | `text/plain` 文件下载 |

二次验证请求示例：

```json
{
  "password": "your-login-password"
}
```

二次验证成功响应示例：

```json
{
  "success": true,
  "verify_token": "..."
}
```

## 账号管理

### GET `/api/accounts`

获取账号列表。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `group_id` | int | 否 | 返回指定分组及所有子分组下的账号 |

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `accounts` | 当前页账号列表 |
| `total` | 当前查询条件下的账号总数 |
| `limit` | 实际使用的单页条数 |
| `offset` | 当前页偏移量 |
| `has_more` | 是否还有下一页 |
| `aliases` | 账号别名列表 |
| `alias_count` | 别名数量 |
| `forward_enabled` | 是否开启转发 |
| `last_refresh_at` | 最近刷新时间 |
| `last_refresh_status` | 最近刷新结果 |
| `last_refresh_error` | 最近刷新错误 |
| `tags` | 标签列表 |

### GET `/api/accounts/search`

搜索账号。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 是 | 搜索关键词，支持主邮箱、备注、标签、别名邮箱；输入多个关键词时可用空格或换行分隔，任一关键词命中即返回，最多 `200` 个关键词 |
| `limit` | int | 否 | 单页条数，最大 `10000` |
| `offset` | int | 否 | 分页偏移量，默认 `0` |
| `sort_by` | string | 否 | 排序字段，支持 `created_at`、`email`、`sort_order` |
| `sort_order` | string | 否 | 排序方向，`asc` 或 `desc`，默认 `desc` |
| `group_id` | int | 否 | 仅搜索指定分组及所有子分组下的账号，不传则搜索全部分组 |
| `tag_ids` | string | 否 | 逗号分隔的标签 ID，仅搜索包含任一标签的账号 |
| `include_untagged` | bool | 否 | 与 `tag_ids` 配合使用，是否包含未打标签账号 |

### POST `/api/accounts`

批量导入账号。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `account_string` | string | 是 | 多行账号文本 |
| `group_id` | int | 否 | 目标分组，默认 `1` |
| `account_format` | string | 否 | Outlook 导入格式：`client_id_refresh_token` 或 `refresh_token_client_id` |
| `provider` | string | 否 | `outlook`、`auto`、`qq`、`163`、`126`、`yahoo`、`aliyun`、`custom` |
| `imap_host` | string | 否 | `provider=custom` 时的 IMAP 服务器 |
| `imap_port` | int | 否 | `provider=custom` 时的 IMAP 端口 |
| `forward_enabled` | bool | 否 | 导入后是否默认启用转发 |
| `remark` | string | 否 | 本次新增账号统一备注，不改变 `account_string` 每行格式 |
| `status` | string | 否 | 本次新增账号统一状态：`active` 或 `inactive` |
| `tag_ids` | array | 否 | 本次新增账号统一绑定的标签 ID 列表 |
| `proxy_url` | string | 否 | 本次新增账号统一使用的账号级主代理；留空继承分组代理 |
| `fallback_proxy_url_1` | string | 否 | 本次新增账号统一使用的账号级回退代理 1 |
| `fallback_proxy_url_2` | string | 否 | 本次新增账号统一使用的账号级回退代理 2 |

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `added_count` | 本次新增账号数量 |
| `skipped_count` | 因重复等原因跳过的账号数量 |
| `invalid_count` | 格式无效的输入行数量 |
| `tagged_count` | 本次成功绑定标签的新增账号数量 |

#### 导入格式

- Outlook: 每行 `邮箱----密码----ClientID----RefreshToken`
- Outlook 反序: 每行 `邮箱----密码----RefreshToken----ClientID`，并设置 `account_format=refresh_token_client_id`
- 非 Outlook IMAP: 每行 `邮箱----IMAP密码`
- 自定义 IMAP: 每行 `邮箱----IMAP密码----IMAP主机----IMAP端口`

#### 请求示例

```json
{
  "account_string": "user@outlook.com----password----client-id----refresh-token",
  "group_id": 1,
  "account_format": "client_id_refresh_token",
  "provider": "outlook",
  "forward_enabled": false,
  "remark": "批次 A",
  "status": "active",
  "tag_ids": [1, 2],
  "proxy_url": "socks5://127.0.0.1:1080",
  "fallback_proxy_url_1": "direct",
  "fallback_proxy_url_2": ""
}
```

### GET `/api/accounts/<account_id>`

获取单个账号详情。

账号详情不会返回 `password` 或 `imap_password` 明文，只返回 `has_password` 和 `has_imap_password` 标记。需要查看已保存的账号密码时，必须调用 `POST /api/accounts/<account_id>/secrets` 并传入当前 Web 登录密码完成二次验证。

#### 响应补充字段

```json
{
  "success": true,
  "account": {
    "id": 1,
    "email": "user@outlook.com",
    "has_password": true,
    "has_imap_password": false,
    "client_id": "xxx",
    "refresh_token": "xxx",
    "aliases": ["alias@example.com", "login@example.com"],
    "alias_count": 2,
    "matched_alias": "",
    "forward_enabled": true,
    "proxy_url": "socks5://127.0.0.1:1080",
    "fallback_proxy_url_1": "direct",
    "fallback_proxy_url_2": "",
    "proxy_override_enabled": true
  }
}
```

#### 查看密码

```http
POST /api/accounts/1/secrets
Content-Type: application/json
```

```json
{
  "password": "web-login-password",
  "field": "password"
}
```

`field` 可选值为 `password` 或 `imap_password`；不传 `field` 时兼容返回两个密码字段。验证通过后返回：

```json
{
  "success": true,
  "secrets": {
    "password": "account-password"
  }
}
```

### PUT `/api/accounts/<account_id>`

更新账号信息。

- 若请求体只有 `status`，则只更新账号状态
- 支持 Outlook 账号和 IMAP 账号
- 现在支持直接在更新账号时一起保存别名
- `proxy_url`、`fallback_proxy_url_1`、`fallback_proxy_url_2` 未传时保留账号现有代理配置；显式传空字符串可清空账号覆盖

#### 请求体常用字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 是 | 邮箱地址 |
| `password` | string | 否 | 账号密码，Outlook 可为空 |
| `client_id` | string | Outlook 必填 | Outlook Client ID |
| `refresh_token` | string | Outlook 必填 | Outlook Refresh Token |
| `account_type` | string | 否 | `outlook` 或 `imap` |
| `provider` | string | 否 | `outlook`、`auto`、`qq`、`163`、`126`、`yahoo`、`aliyun`、`custom` |
| `imap_host` | string | 自定义 IMAP 必填 | 自定义 IMAP 服务器 |
| `imap_port` | int | 否 | IMAP 端口 |
| `imap_password` | string | IMAP 必填 | IMAP 密码 |
| `group_id` | int | 否 | 分组 ID |
| `remark` | string | 否 | 备注 |
| `status` | string | 否 | `active` 等状态值 |
| `forward_enabled` | bool | 否 | 是否开启转发 |
| `proxy_url` | string | 否 | 账号级主代理；留空且回退代理也为空时继承分组代理 |
| `fallback_proxy_url_1` | string | 否 | 账号级回退代理 1，支持 `direct` / `直连` |
| `fallback_proxy_url_2` | string | 否 | 账号级回退代理 2，支持 `direct` / `直连` |
| `aliases` | array<string> | 否 | 账号别名列表；若传入则按新列表整体替换 |

#### 请求示例

```json
{
  "email": "user@outlook.com",
  "client_id": "xxx",
  "refresh_token": "xxx",
  "group_id": 1,
  "remark": "主账号",
  "status": "active",
  "forward_enabled": true,
  "proxy_url": "socks5://127.0.0.1:1080",
  "fallback_proxy_url_1": "direct",
  "fallback_proxy_url_2": "",
  "aliases": [
    "alias@example.com",
    "login@example.com"
  ]
}
```

### POST `/api/accounts/<account_id>/reauthorize`

为已有 Outlook OAuth 账号重新授权。该接口只支持 Outlook 账号，不支持 IMAP 账号。

请求体：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `redirected_url` | string | 是 | Microsoft 授权完成后浏览器地址栏中的完整回调 URL |

接口会从 `redirected_url` 解析授权码，向 Microsoft 换取新的 Refresh Token，随后只更新目标账号的 `client_id`、加密后的 `refresh_token`、`refresh_token_updated_at` 和刷新状态字段。邮箱、密码、分组、状态、转发、代理、备注、别名、标签等字段不会被该接口修改。

授权信息保存成功后，接口会清理旧的刷新失败错误，并立即触发一次单账号 Token 刷新验证。响应中的 `success` 表示授权信息已保存；`validation.success` 表示自动刷新验证是否通过。

请求示例：

```json
{
  "redirected_url": "http://localhost:8080/?code=..."
}
```

刷新验证成功响应示例：

```json
{
  "success": true,
  "message": "重新授权成功，Token 刷新验证通过",
  "authorization_updated": true,
  "validation": {
    "success": true,
    "status": "success",
    "message": "Token 刷新成功"
  }
}
```

刷新验证失败响应示例：

```json
{
  "success": true,
  "message": "重新授权已保存，但自动刷新验证失败",
  "authorization_updated": true,
  "validation": {
    "success": false,
    "status": "failed",
    "error": {
      "code": "TOKEN_REFRESH_FAILED",
      "message": "Token 刷新失败",
      "type": "RefreshTokenError",
      "status": 400
    },
    "error_message": "Graph 刷新失败: ..."
  }
}
```

常见错误：

- `ACCOUNT_NOT_FOUND`: 账号不存在
- `ACCOUNT_REAUTH_UNSUPPORTED`: IMAP 账号不支持重新授权
- `OAUTH_EXCHANGE_FAILED`: 回调 URL 无效或 Microsoft 换取 Token 失败
- `ACCOUNT_REAUTH_SAVE_FAILED`: 新授权信息保存失败

### POST `/api/accounts/batch-update-group`

批量修改账号分组。

#### 请求示例

```json
{
  "account_ids": [1, 2, 3],
  "group_id": 5
}
```

### POST `/api/accounts/batch-update-forwarding`

批量开启或关闭账号转发。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `account_ids` | array<int> | 是 | 账号 ID 列表 |
| `forward_enabled` | bool | 是 | `true` 表示开启转发，`false` 表示关闭转发 |

#### 请求示例

```json
{
  "account_ids": [1, 2, 3],
  "forward_enabled": true
}
```

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `updated_count` | 实际状态发生变化的账号数量 |
| `updated_accounts` | 被更新的账号列表 |
| `unchanged_count` | 原本就处于目标状态的账号数量 |
| `missing_ids` | 未命中的账号 ID |

### POST `/api/accounts/batch-update-proxy`

批量设置或清空账号级代理。账号级代理三项全空时，该账号会继续继承所属分组代理；任一项非空时，账号级配置优先于分组配置。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `account_ids` | array<int> | 是 | 账号 ID 列表 |
| `proxy_url` | string | 否 | 账号级主代理，支持 `direct` / `直连` |
| `fallback_proxy_url_1` | string | 否 | 回退代理 1 |
| `fallback_proxy_url_2` | string | 否 | 回退代理 2 |

#### 请求示例

```json
{
  "account_ids": [1, 2, 3],
  "proxy_url": "socks5://127.0.0.1:1080",
  "fallback_proxy_url_1": "direct",
  "fallback_proxy_url_2": ""
}
```

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `updated_count` | 实际代理配置发生变化的账号数量 |
| `updated_accounts` | 被更新的账号列表 |
| `unchanged_count` | 原本就处于目标代理配置的账号数量 |
| `missing_ids` | 未命中的账号 ID |

### GET `/api/accounts/<account_id>/aliases`

获取某个账号的别名列表。

### PUT `/api/accounts/<account_id>/aliases`

整体替换某个账号的别名列表。

#### 请求示例

```json
{
  "aliases": [
    "alias@example.com",
    "login@example.com"
  ]
}
```

### DELETE `/api/accounts/<account_id>`

按账号 ID 删除账号。

### DELETE `/api/accounts/email/<email_addr>`

按邮箱地址删除账号。

### POST `/api/accounts/batch-delete`

批量删除账号。

#### 请求体

```json
{
  "account_ids": [1, 2, 3]
}
```

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `deleted_count` | 实际删除数量 |
| `deleted_accounts` | 已删除账号列表 |
| `missing_ids` | 请求中存在但未命中的账号 ID |

## 标签管理

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/tags` | 无 | 获取所有标签 |
| POST | `/api/tags` | JSON: `name`、`color?` | 创建标签 |
| DELETE | `/api/tags/<tag_id>` | 路径参数 `tag_id` | 删除标签 |
| POST | `/api/accounts/tags` | JSON: `account_ids`、`tag_id`、`action` | 批量给账号加标签或移除标签 |
| POST | `/api/temp-emails/tags` | JSON: `temp_email_ids`、`tag_id`、`action` | 批量给临时邮箱加标签或移除标签 |

批量标签管理请求示例：

```json
{
  "account_ids": [1, 2, 3],
  "tag_id": 8,
  "action": "add"
}
```

临时邮箱批量标签请求示例：

```json
{
  "temp_email_ids": [11, 12],
  "tag_id": 8,
  "action": "remove"
}
```

## 项目管理

项目接口用于按 `project_key` 管理“邮箱在某个项目下的独立状态”。

- 同一个邮箱可以同时存在于多个项目中
- 项目内状态独立维护，互不影响
- 当前项目状态包括：
  - `toClaim`：可领取
  - `claiming`：领取中
  - `done`：已成功消费，不再自动分配
  - `failed`：最近一次消费失败，需人工重置后才可再次分配
  - `removed`：人工移出项目范围
  - `deleted`：系统主表里的账号已删除，但项目历史仍保留

### GET `/api/projects`

获取项目列表。

#### 成功响应示例

```json
{
  "success": true,
  "data": {
    "projects": [
      {
        "id": 1,
        "name": "GPT 注册",
        "project_key": "gpt",
        "description": "GPT 注册项目",
        "scope_mode": "groups",
        "use_alias_email": false,
        "status": "active",
        "group_ids": [1, 2],
        "total_count": 500,
        "to_claim_count": 120,
        "claiming_count": 5,
        "failed_count": 8,
        "done_count": 360,
        "removed_count": 15,
        "deleted_count": 3,
        "last_scope_synced_at": "2026-04-15T09:30:00+00:00",
        "created_at": "2026-04-10 08:00:00",
        "updated_at": "2026-04-15T09:30:00+00:00"
      }
    ]
  }
}
```

### GET `/api/projects/<project_key>`

获取单个项目详情。

### POST `/api/projects/start`

启动项目。

这个接口合并了“创建项目”和“补全项目范围”两种语义：

- 如果 `project_key` 不存在：
  - 创建新项目
  - 保存项目范围
  - 把范围内邮箱补入项目
- 如果 `project_key` 已存在：
  - 视为再次启动同一项目
  - 默认沿用原有范围
  - 如果本次显式传了 `group_ids`，会更新范围后再补全
  - 只补新增邮箱，不会重置已有项目状态

删除补偿规则：

- 启动项目时会检查项目历史中已失联的账号
- 若项目记录对应的账号已从 `accounts` 主表删除，则该项目记录会标为 `deleted`
- 若同一个邮箱地址后来被重新导入系统，启动项目时会按邮箱地址复用旧项目记录，而不是把它当成全新邮箱

别名邮箱规则：

- `use_alias_email=false` 时，项目按主邮箱地址入池
- `use_alias_email=true` 时，优先按账号别名邮箱入池
- 若某个账号没有配置别名，则在 `use_alias_email=true` 时仍会回退使用主邮箱地址
- 再次启动已存在项目时，如果不显式传 `use_alias_email`，会沿用当前项目配置

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `project_key` | string | 是 | 项目标识，内部会转成小写并去掉首尾空格 |
| `name` | string | 否 | 项目名称。首次创建时不传则默认使用 `project_key` |
| `description` | string | 否 | 项目描述 |
| `group_ids` | array<int> | 否 | 项目范围分组列表；会包含每个分组及其所有子分组账号；不传时首次创建默认为全量邮箱范围 |
| `use_alias_email` | bool | 否 | 是否优先把别名邮箱加入项目；默认 `false` |

#### 请求示例

首次创建分组范围项目：

```json
{
  "project_key": "gpt",
  "name": "GPT 注册",
  "description": "GPT 注册项目",
  "group_ids": [1, 2],
  "use_alias_email": true
}
```

首次创建全量范围项目：

```json
{
  "project_key": "google",
  "name": "Google 注册"
}
```

再次启动已有项目：

```json
{
  "project_key": "gpt"
}
```

#### 成功响应示例

```json
{
  "success": true,
  "message": "项目已启动",
  "data": {
    "id": 1,
    "name": "GPT 注册",
    "project_key": "gpt",
    "description": "GPT 注册项目",
    "scope_mode": "groups",
    "use_alias_email": true,
    "status": "active",
    "group_ids": [1, 2],
    "total_count": 560,
    "to_claim_count": 120,
    "claiming_count": 5,
    "failed_count": 8,
    "done_count": 360,
    "removed_count": 15,
    "deleted_count": 3,
    "created": false,
    "added_count": 128
  }
}
```

#### 返回重点字段

| 字段 | 说明 |
| --- | --- |
| `created` | 本次是否首次创建该项目 |
| `added_count` | 本次启动新补入的邮箱数量 |
| `deleted_count` | 本次启动过程中被标记为 `deleted` 的项目邮箱数量 |
| `use_alias_email` | 当前项目是否按别名邮箱入池 |

### GET `/api/projects/<project_key>/accounts`

获取某个项目下的邮箱列表。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 否 | 按项目状态过滤，如 `toClaim`、`failed`、`done` |
| `group_id` | int | 否 | 按当前分组或项目来源分组过滤；会包含该分组及所有子分组 |
| `provider` | string | 否 | 按邮箱 provider 过滤 |
| `keyword` | string | 否 | 在邮箱地址、备注里做模糊搜索 |

#### 成功响应示例

```json
{
  "success": true,
  "data": {
      "project": {
        "id": 1,
        "name": "GPT 注册",
        "project_key": "gpt",
        "description": "GPT 注册项目",
        "scope_mode": "groups",
        "use_alias_email": true,
        "status": "active",
        "group_ids": [1, 2],
      "total_count": 560,
      "to_claim_count": 120,
      "claiming_count": 5,
      "failed_count": 8,
      "done_count": 360,
      "removed_count": 15,
      "deleted_count": 3
    },
    "accounts": [
      {
        "project_account_id": 101,
        "account_id": 12,
        "email": "alias@example.com",
        "primary_email": "user@example.com",
        "normalized_email": "alias@example.com",
        "provider": "outlook",
        "account_type": "outlook",
        "group_id": 1,
        "group_name": "默认分组",
        "remark": "",
        "project_status": "failed",
        "account_status": "active",
        "caller_id": "",
        "task_id": "",
        "claim_token": "",
        "claimed_at": "",
        "lease_expires_at": "",
        "last_result": "failed",
        "last_result_detail": "provider blocked",
        "claim_count": 2,
        "first_claimed_at": "2026-04-15T09:30:00+00:00",
        "last_claimed_at": "2026-04-15T09:35:00+00:00",
        "done_at": "",
        "created_at": "2026-04-15T09:20:00+00:00",
        "updated_at": "2026-04-15T09:36:00+00:00"
      }
    ]
  }
}
```

### POST `/api/projects/<project_key>/claim-random`

从项目里随机领取一个可用邮箱。

当前实现会从项目内 `status='toClaim'` 的邮箱中选取一个，并确保该邮箱没有被其他项目中的 `claiming` 记录占用。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `caller_id` | string | 是 | 调用方标识 |
| `task_id` | string | 是 | 当前任务标识 |
| `lease_seconds` | int | 否 | 租期秒数，默认 `600`，最大 `3600` |

#### 请求示例

```json
{
  "caller_id": "worker-1",
  "task_id": "task-001",
  "lease_seconds": 600
}
```

#### 成功响应示例

```json
{
  "success": true,
  "data": {
    "project_key": "gpt",
    "project_account_id": 101,
    "account_id": 12,
    "email": "alias@example.com",
    "primary_email": "user@example.com",
    "group_id": 1,
    "provider": "outlook",
    "account_type": "outlook",
    "remark": "",
    "claim_token": "pclm_xxx",
    "claimed_at": "2026-04-15T10:00:00+00:00",
    "lease_expires_at": "2026-04-15T10:10:00+00:00"
  }
}
```

无可领取邮箱时，当前实现返回：

```json
{
  "success": false,
  "error": "没有可领取的项目邮箱"
}
```

### POST `/api/projects/<project_key>/complete-success`

把当前领取中的项目邮箱标记为成功。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `account_id` | int | 是 | 账号 ID |
| `claim_token` | string | 是 | 领取时返回的 token |
| `caller_id` | string | 否 | 调用方标识 |
| `task_id` | string | 否 | 任务标识 |
| `detail` | string | 否 | 成功说明 |

### POST `/api/projects/<project_key>/complete-failed`

把当前领取中的项目邮箱标记为失败。

- 状态会从 `claiming` 变成 `failed`
- `failed` 不会自动再次参与分配
- 需要人工调用 `/reset-failed` 后才能再次领取

#### 请求示例

```json
{
  "account_id": 12,
  "claim_token": "pclm_xxx",
  "caller_id": "worker-1",
  "task_id": "task-001",
  "detail": "provider blocked"
}
```

### POST `/api/projects/<project_key>/release`

主动释放领取中的项目邮箱。

- 状态会从 `claiming` 回到 `toClaim`
- 适合任务中断、主动放弃等场景

### POST `/api/projects/<project_key>/reset-failed`

人工把 `failed` 邮箱重置回 `toClaim`。

#### 请求示例

```json
{
  "account_id": 12,
  "detail": "人工允许重试"
}
```

### POST `/api/projects/<project_key>/remove-account`

人工把项目邮箱移出项目范围。

- 目标状态变成 `removed`
- 若当前状态是 `claiming`，会拒绝移出

#### 请求示例

```json
{
  "account_id": 12,
  "detail": "人工移出项目"
}
```

### POST `/api/projects/<project_key>/restore-account`

人工把 `removed` 项目邮箱恢复回 `toClaim`。

#### 请求示例

```json
{
  "account_id": 12,
  "detail": "人工恢复到项目"
}
```

## 刷新与转发运维

### Token 刷新

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/accounts/<account_id>/refresh` | 路径参数 `account_id` | 刷新单个 Outlook 账号 Token |
| POST | `/api/accounts/refresh-selected` | JSON: `account_ids: number[]` | 刷新选中的 Outlook 账号，自动跳过 IMAP 或不存在的账号 |
| POST | `/api/accounts/refresh-selected-stream` | JSON: `account_ids: number[]` | 初始化选中账号流式刷新任务，返回 `task_id` 和 `stream_url` |
| GET | `/api/accounts/refresh-selected-stream/<task_id>` | 路径参数 `task_id` | 订阅选中账号流式刷新任务，返回 `text/event-stream` |
| GET | `/api/accounts/refresh-all` | 无 | 刷新全部 Outlook 账号，返回 `text/event-stream` |
| POST | `/api/accounts/<account_id>/retry-refresh` | 路径参数 `account_id` | 重试单个失败账号刷新 |
| GET | `/api/accounts/refresh-failed-stream` | 无 | 流式重试当前失败账号，返回 `text/event-stream` |
| POST | `/api/accounts/refresh-failed` | 无 | 重试最近一次刷新失败的账号 |
| GET | `/api/accounts/trigger-scheduled-refresh` | Query: `force=true/false` | 手动触发一次“定时刷新”逻辑，返回 `text/event-stream` |
| POST | `/api/accounts/stop-full-refresh` | 无 | 请求停止当前全量刷新任务 |

`/api/accounts/refresh-all`、`/api/accounts/refresh-failed-stream`、`/api/accounts/refresh-selected-stream/<task_id>`、`/api/accounts/trigger-scheduled-refresh` 都会返回 SSE 事件流，常见事件类型包括：

- `start`
- `progress`
- `delay`
- `complete`

选中账号流式刷新需先初始化任务：

```json
{
  "account_ids": [1, 2, 3]
}
```

`POST /api/accounts/refresh-selected-stream` 成功时返回：

```json
{
  "success": true,
  "task_id": "task-token",
  "stream_url": "/api/accounts/refresh-selected-stream/task-token"
}
```

随后使用 `EventSource` 订阅 `stream_url`。该任务使用进程内短期状态保存，服务部署需保持单 worker；如果任务不存在或已过期，SSE 会返回 `type=error` 事件。

`POST /api/accounts/stop-full-refresh` 成功时返回：

```json
{
  "success": true,
  "message": "已请求停止当前全量刷新任务"
}
```

若当前没有进行中的全量刷新任务，会返回 HTTP `409`：

```json
{
  "success": false,
  "message": "当前没有进行中的全量刷新任务"
}
```

`POST /api/accounts/refresh-selected` 请求示例：

```json
{
  "account_ids": [1, 2, 3]
}
```

该接口会返回：

- `requested_count`
- `processed_count`
- `success_count`
- `failed_count`
- `skipped_count`
- `failed_list`
- `skipped_list`

### 刷新日志与统计

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/accounts/refresh-logs` | Query: `limit`、`offset` | 获取所有刷新日志 |
| GET | `/api/accounts/<account_id>/refresh-logs` | Query: `limit`、`offset` | 获取单个账号刷新日志 |
| GET | `/api/accounts/refresh-logs/failed` | 无 | 获取当前失败状态邮箱快照 |
| GET | `/api/accounts/refresh-stats` | 无 | 获取当前刷新统计快照 |
| GET | `/api/accounts/refresh-status-list` | Query: `q`、`status`、`page`、`page_size` | 获取 Token 刷新管理邮箱列表 |

`GET /api/accounts/refresh-logs/failed` 返回的是“当前仍处于失败状态的邮箱快照”，不再是历史失败日志列表。

`GET /api/accounts/refresh-status-list` 查询参数：

- `q`
- `status=all|success|failed|never`
- `page`：最小为 `1`
- `page_size`：最小为 `1`，最大为 `10000`

### 转发日志与触发

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/accounts/forwarding-logs` | Query: `limit`、`offset` | 获取最近转发记录 |
| GET | `/api/accounts/forwarding-logs/failed` | Query: `limit` | 获取最近失败转发记录 |
| GET | `/api/accounts/<account_id>/forwarding-logs` | Query: `limit`、`offset`、`failed_only` | 获取单个账号转发记录 |
| POST | `/api/accounts/trigger-forwarding-check` | 无 | 立即触发一次转发检查 |
| POST | `/api/accounts/<account_id>/forwarding/reset-cursor` | JSON: `mode?`、`lookback_minutes?`、`trigger_check?` | 回退或清空单个账号的转发游标，并可选立即触发一次重扫 |

`POST /api/accounts/<account_id>/forwarding/reset-cursor` 请求示例：

```json
{
  "mode": "window",
  "lookback_minutes": 30,
  "trigger_check": true
}
```

字段说明：

- `mode=window`：按回看窗口重置游标
- `mode=clear`：清空游标
- `lookback_minutes`：回看分钟数，未传时按系统窗口逻辑处理
- `trigger_check`：是否在重置后立即触发一次转发检查，默认 `true`

## 邮件接口

### GET `/api/emails/<email_addr>`

内部邮件列表接口。支持主邮箱或别名邮箱；若邮箱包含 `+`，会先按完整地址匹配，未命中时再按本地部分从右到左逐级去掉 `+suffix` 回退匹配，兼容主邮箱和别名邮箱。若域名是 `gmail.com` 或 `googlemail.com`，原后缀候选都未命中后会继续回退到另一个后缀。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `folder` | string | 否 | `inbox`、`junkemail`、`deleteditems`、`all` |
| `skip` | int | 否 | 分页偏移，默认 `0`；非数字使用默认值，负数按 `0` 处理 |
| `top` | int | 否 | 返回数量，默认 `20`；非数字使用默认值，负数按 `0` 处理。远程读取最大 `50`，本地保留读取不额外截断 |
| `source` | string | 否 | 传 `local` 时只读取普通邮箱本地保留列表；需要 `normal_mail_local_retention_enabled=true` |
| `local_only` | bool | 否 | `1` / `true` / `yes` / `on` 等价于 `source=local` |
| `subject_contains` | string | 否 | 仅保留主题中包含该关键字的邮件，读取时保留 `+` 字符 |
| `from_contains` | string | 否 | 仅保留发件人中包含该关键字的邮件，读取时保留 `+` 字符 |
| `keyword` | string | 否 | 在主题、预览、正文中做进一步关键字过滤，读取时保留 `+` 字符 |

当 `folder=all` 时，行为与对外 API 一致：同时抓取 `inbox` 与 `junkemail`，按时间合并排序。

成功响应会额外包含 `requested_email`、`resolved_email`；当请求邮箱命中别名时，还会包含 `matched_alias`。如果使用 Gmail/Googlemail 或 plus-address 回退候选命中，还会包含 `resolved_query_email`、`fallback_used`、`fallback_email` 等字段。

#### 列表项字段

`emails` 数组中的每个对象至少包含以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 邮件 ID |
| `subject` | string | 邮件主题 |
| `from` | string | 发件人地址 |
| `to` | string | 收件人地址，多个地址用 `, ` 拼接 |
| `date` | string | 收件时间 |
| `is_read` | bool | 是否已读 |
| `has_attachments` | bool | 是否有附件 |
| `body_preview` | string | 邮件预览 |
| `folder` | string | 所属文件夹 |
| `id_mode` | string | 消息 ID 模式：Graph 为 `graph`，OAuth IMAP 常见为 `uid` 或 `sequence`，用于详情、标记已读和附件下载复用同一种 ID 语义 |

### GET `/api/email/<email_addr>/<message_id>`

获取单封邮件详情。`email` 参数同样支持传主邮箱或别名邮箱。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `folder` | string | 否 | 当前邮件所在文件夹，默认 `inbox` |
| `method` | string | 否 | 优先取详情的方式，常见为 `graph`；传 `imap` 可走 Outlook OAuth IMAP 回退 |
| `id_mode` | string | 否 | OAuth IMAP 消息 ID 模式，支持 `uid`、`sequence`；缺省或非法值按 `uid` 处理 |
| `source` | string | 否 | 传 `local` 时优先返回已缓存的本地保留详情正文 |
| `prefer_local` | bool | 否 | `1` / `true` / `yes` / `on` 等价于 `source=local` |

#### 返回字段

`email` 对象至少包含以下字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 邮件 ID |
| `subject` | string | 邮件主题 |
| `from` | string | 发件人 |
| `to` | string | 收件人，多个地址用 `, ` 拼接 |
| `cc` | string | 抄送，可能为空 |
| `date` | string | 收件时间 |
| `body` | string | 邮件正文 |
| `body_type` | string | `html` 或 `text` |
| `has_attachments` | bool | 是否有附件 |
| `attachments` | array<object> | 附件列表 |

`attachments` 中每个对象包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 附件 ID，下载附件时使用 |
| `name` | string | 附件文件名 |
| `content_type` | string | MIME 类型 |
| `size` | int | 附件大小，单位字节 |
| `is_inline` | bool | 是否为内联附件 |
| `content_id` | string | 内联附件的 Content-ID，没有时为空 |

### GET `/api/email/<email_addr>/<message_id>/attachments/<attachment_id>`

下载单个邮件附件。返回文件流，并带 `Content-Disposition: attachment` 响应头。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `folder` | string | 否 | 当前邮件所在文件夹，默认 `inbox` |
| `method` | string | 否 | Outlook 账号优先使用 `graph`，传 `imap` 时走 IMAP 下载 |
| `id_mode` | string | 否 | OAuth IMAP 附件下载使用的消息 ID 模式，支持 `uid`、`sequence`；缺省按 `uid` 处理 |

### GET `/api/email/<email_addr>/<message_id>/attachments/download-all`

打包下载当前邮件的全部附件。返回 `application/zip` 文件流，下载文件名为 `attachments.zip`。

ZIP 内文件名使用附件原始文件名；如果多个附件同名，会自动追加序号避免覆盖。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `folder` | string | 否 | 当前邮件所在文件夹，默认 `inbox` |
| `method` | string | 否 | Outlook 账号优先使用 `graph`，传 `imap` 时走 IMAP 下载 |
| `id_mode` | string | 否 | OAuth IMAP 附件下载使用的消息 ID 模式，支持 `uid`、`sequence`；缺省按 `uid` 处理 |

### POST `/api/emails/mark-read`

批量标记邮件为已读。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 是 | 主邮箱或别名邮箱 |
| `method` | string | 否 | 默认 `graph`，可传 `imap` |
| `folder` | string | 否 | 默认文件夹，默认 `inbox` |
| `ids` | array<string> | 条件必填 | 简写模式，直接传邮件 ID 数组 |
| `items` | array<object> | 条件必填 | 完整模式，可为每封邮件单独指定文件夹和 ID 模式 |

`items` 模式下每项支持：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` / `message_id` | string | 邮件 ID |
| `folder` | string | `inbox`、`junkemail`、`deleteditems`、`all` |
| `id_mode` | string | `graph`、`uid`、`sequence` |

#### 请求示例

简写模式：

```json
{
  "email": "user@outlook.com",
  "ids": ["AAMk...", "AAMk..."],
  "folder": "inbox"
}
```

完整模式：

```json
{
  "email": "user@outlook.com",
  "method": "imap",
  "items": [
    {
      "id": "12345",
      "folder": "inbox",
      "id_mode": "uid"
    },
    {
      "id": "AAMk...",
      "folder": "junkemail",
      "id_mode": "graph"
    }
  ]
}
```

#### 响应重点字段

| 字段 | 说明 |
| --- | --- |
| `success` | 只有全部成功才为 `true` |
| `success_count` | 成功标记为已读的邮件数量 |
| `failed_count` | 失败数量 |
| `updated_ids` | 已成功更新的邮件 ID 列表 |
| `errors` | 失败详情列表 |
| `error` | 第一条失败信息，兼容旧前端逻辑 |

### POST `/api/emails/retain-bodies`

为已保留的普通邮箱列表行补齐详情正文缓存，供本地优先列表、新邮件提示合并后和后续离线详情回退使用。该接口只在 `normal_mail_local_retention_enabled=true` 时执行；关闭时返回 `local_retention_enabled=false` 并跳过所有项目。

#### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | string | 是 | 普通邮箱账号地址或别名地址 |
| `folder` | string | 否 | 默认文件夹，默认 `inbox`；单个 `items` 项可覆盖 |
| `method` | string | 否 | 默认读取方式，默认 `graph`；单个 `items` 项可覆盖 |
| `items` | array | 否 | 待补齐的列表项。每项可包含 `id` / `message_id`、`folder`、`method`、`id_mode` |
| `ids` | array | 否 | 兼容旧调用；当未传 `items` 时作为待补齐 ID 列表 |

#### 响应字段

| 字段 | 说明 |
| --- | --- |
| `cached_count` | 本次成功补齐正文的数量 |
| `skipped_count` | 已有缓存、参数不完整或超出服务端上限而跳过的数量 |
| `failed_count` | 远程详情读取失败的数量 |
| `limit` | 单次最多补齐的服务端上限 |
| `results` | 单项补齐结果 |
| `errors` | 单项失败原因 |

### POST `/api/emails/delete`

批量删除邮件。

#### 请求体

```json
{
  "email": "user@outlook.com",
  "ids": ["AAMk...", "AAMk..."]
}
```

说明：

- Outlook 账号会优先走 Graph API，失败后按逻辑回退 IMAP
- IMAP 账号当前不支持批量删除

## 临时邮箱

### 列表、导入、渠道域名

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/temp-emails` | 无 | 获取所有临时邮箱，列表项包含 `tags` 字段 |
| POST | `/api/temp-emails/import` | JSON: `account_string`、`provider`、`tag_ids?` | 批量导入临时邮箱；Cloudflare 导入成功的邮箱可同步绑定标签 |
| POST | `/api/temp-emails/batch-delete` | JSON: `temp_email_ids` | 批量删除临时邮箱 |
| GET | `/api/duckmail/domains` | 无 | 获取 DuckMail 可用域名 |
| GET | `/api/cloudflare/channels` | 无 | 获取 Cloudflare 渠道列表 |
| POST | `/api/cloudflare/channels` | JSON: 渠道配置 | 创建 Cloudflare 渠道 |
| PUT | `/api/cloudflare/channels/<id>` | JSON: 渠道配置 | 更新 Cloudflare 渠道 |
| DELETE | `/api/cloudflare/channels/<id>` | 无 | 删除未被引用的 Cloudflare 渠道 |
| POST | `/api/cloudflare/channels/<id>/test` | 无 | 测试 Cloudflare 渠道管理员 API 连接 |
| GET | `/api/cloudflare/domains` | Query: `channel_id` | 获取指定 Cloudflare 渠道可用域名 |
| GET | `/api/cloudflare/messages` | Query: `channel_id?`、`limit?`、`offset?`、`address?` | 使用指定或默认 Cloudflare 渠道的管理员接口查看该渠道全部邮件，可选按收件地址过滤 |
| POST | `/api/temp-emails/import-cloudflare-addresses` | JSON: `cloudflare_channel_id`、`tag_ids?`、`page_size?`、`stream?` | 从指定 Cloudflare 渠道自动拉取地址列表导入，通过管理员 API 管理；`stream=true` 时返回 Server-Sent Events 流式进度 |
| POST | `/api/temp-emails/generate-batch` | JSON: `provider=cloudflare`、`count`、`channel_id?`、`domain?`、`usernames?`、`tag_ids?` | 批量生成 Cloudflare 临时邮箱，通过管理员 API 管理 |
| POST | `/api/cloudflare/ai-usernames/test` | JSON: AI 草稿配置、`count` | 使用未保存或已保存的配置测试 AI 用户名生成 |
| POST | `/api/cloudflare/ai-usernames/generate` | JSON: `count` | 使用已保存且启用的 AI 配置生成严格等量用户名 |

`/api/temp-emails/import` 的导入格式：

- `provider=gptmail`: 每行一个邮箱
- `provider=duckmail`: 每行 `邮箱----密码`
- `provider=cloudflare`: 每行一个邮箱地址，使用请求中的 `cloudflare_channel_id` 绑定渠道；所有 Cloudflare 邮箱统一通过渠道管理员 API 管理，不再使用 JWT；兼容旧格式 `邮箱----JWT`，会自动提取邮箱部分

### POST `/api/temp-emails/generate`

生成新的临时邮箱。

#### 请求体

| provider | 需要字段 | 说明 |
| --- | --- | --- |
| `gptmail` | `prefix?`、`domain?` | 不传则走默认随机生成 |
| `duckmail` | `domain`、`username`、`password` | 用户名至少 3 位，密码至少 6 位 |
| `cloudflare` | `channel_id`、`domain?`、`username?` | `channel_id` 指定 Cloudflare 渠道；`username` 可留空随机生成 |

#### 请求示例

```json
{
  "provider": "duckmail",
  "domain": "example.com",
  "username": "demo123",
  "password": "secret123"
}
```

### POST `/api/temp-emails/generate-batch`

批量生成 Cloudflare 临时邮箱。当前仅支持 `provider=cloudflare`。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `provider` | string | 是 | 固定为 `cloudflare` |
| `count` | int | 是 | 创建数量，范围 `1-50` |
| `channel_id` | int/string | 否 | Cloudflare 渠道 ID；不传时使用默认渠道 |
| `domain` | string | 否 | 指定邮箱域名；不传时使用渠道第一个域名 |
| `usernames` | array<string> | 否 | 显式用户名列表。空或不传时随机生成；非空时清洗后数量必须等于 `count`，且不能重复 |
| `tag_ids` | array<int> | 否 | 为成功创建的临时邮箱绑定存在的标签 |

用户名清洗规则：转小写；含 `@` 时取 `@` 前缀；删除所有非 `a-z0-9` 字符；清洗后长度必须至少 3；最多保留 32 个字符。

#### 请求示例

```json
{
  "provider": "cloudflare",
  "channel_id": 1,
  "domain": "mail.example.com",
  "count": 3,
  "usernames": ["alpha", "beta@example.com", "sales.ops"],
  "tag_ids": [2, 5]
}
```

#### 成功或部分成功响应示例

```json
{
  "success": true,
  "emails": [
    "alpha@mail.example.com",
    "beta@mail.example.com"
  ],
  "created_count": 2,
  "failed_count": 1,
  "failures": [
    {
      "index": 3,
      "username": "salesops",
      "error": "upstream rejected"
    }
  ],
  "tagged_count": 2,
  "message": "已创建 2 个 Cloudflare 临时邮箱"
}
```

如果全部创建失败，`success=false`，并返回第一个失败原因到 `error`。

### POST `/api/cloudflare/ai-usernames/test`

使用草稿配置测试 AI 用户名生成，不创建邮箱、不保存生成结果。可用于设置页保存前测试。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `api_url` | string | 是 | OpenAI-compatible API 地址；可传基础 `/v1` 地址，后端会补 `/chat/completions` |
| `model` | string | 是 | 模型名称 |
| `api_key` | string | 否 | AI API Key；省略时尝试使用已保存密钥 |
| `prompt` | string | 否 | 提示词模板，支持 `{count}` 和 `{seed}` |
| `count` | int | 否 | 期望数量，范围 `1-50`，默认 `5` |

### POST `/api/cloudflare/ai-usernames/generate`

使用已保存且已启用的 Cloudflare AI 用户名配置生成用户名列表。该接口只返回用户名，不创建邮箱、不绑定标签。

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `count` | int | 是 | 期望数量，范围 `1-50` |

该接口要求 AI 原始返回数量和清洗后的数量都严格等于 `count`。数量不足、过多、重复或清洗后无效都会返回 `success=false`，不会随机补齐或截断。

### 临时邮箱邮件接口

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| DELETE | `/api/temp-emails/<email_addr>` | 路径参数 `email_addr` | 删除临时邮箱 |
| GET | `/api/temp-emails/<email_addr>/messages` | 路径参数 `email_addr` | 获取临时邮箱邮件列表 |
| GET | `/api/temp-emails/<email_addr>/messages/<message_id>` | 路径参数 | 获取临时邮件详情 |
| DELETE | `/api/temp-emails/<email_addr>/messages/<message_id>` | 路径参数 | 当前返回“单封删信功能已暂时关闭” |
| DELETE | `/api/temp-emails/<email_addr>/clear` | 路径参数 | 当前返回“清空功能已暂时关闭” |
| POST | `/api/temp-emails/<email_addr>/refresh` | 路径参数 | 主动刷新一次临时邮箱邮件 |

`GET /messages` 与 `POST /refresh` 都会返回统一结构的 `emails` 列表。`POST /refresh` 还会包含 `new_count`，表示本次新保存的邮件数量。

### Cloudflare 渠道管理

Cloudflare Temp Email 支持多渠道配置。每个渠道包含 `name`、`worker_domain`、`email_domains`、`admin_password`、`enabled`、`is_default`。`email_domains` 可选，留空时渠道仍可保存但不能在生成邮箱时自动选择域名；管理员密码只在保存时提交；列表响应只返回 `admin_password_configured`。

创建渠道：

```http
POST /api/cloudflare/channels
```

```json
{
  "name": "cfmail-us",
  "worker_domain": "cfmail-us.example.workers.dev",
  "email_domains": "mail-us.example.com, alt-us.example.com",
  "admin_password": "ADMIN_PASSWORD",
  "enabled": true,
  "is_default": true
}
```

更新已有渠道时 `admin_password` 可留空，表示保留原密码；`email_domains` 也可留空，域名查询接口会返回成功响应和空列表。删除渠道前系统会检查是否仍有 Cloudflare 临时邮箱引用该渠道；被引用的渠道不能删除，可以先停用。

### GET `/api/cloudflare/messages`

查看指定 Cloudflare 渠道 Worker 的全部邮件；未传 `channel_id` 时使用默认 Cloudflare 渠道。该接口需要 Web 登录 session，不使用对外 API Key；它不同于普通邮箱的 `folder=all`，后者只聚合某个普通邮箱账号的收件箱和垃圾邮件。本接口不提供跨 Cloudflare 渠道聚合视图。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `channel_id` | int | 否 | Cloudflare 渠道 ID；不传时使用默认渠道 |
| `limit` | int | 否 | 返回数量，默认 `50`，最大 `100` |
| `offset` | int | 否 | 分页偏移，默认 `0` |
| `address` | string | 否 | 收件地址过滤；不传时查看该渠道 Worker 全部邮件 |

当 `address` 是 `@gmail.com` 或 `@googlemail.com`，且第一次地址过滤查询成功但返回 0 封邮件时，会在同一渠道内自动用另一个后缀重试。响应中的 `channel_id`、`channel_name`、`requested_email`、`queried_email`、`fallback_used` 会说明实际查询范围和地址。

#### 成功响应示例

```json
{
  "success": true,
  "method": "Cloudflare Admin",
  "channel_id": 1,
  "channel_name": "cfmail-us",
  "requested_email": "user@gmail.com",
  "queried_email": "user@googlemail.com",
  "fallback_used": true,
  "limit": 50,
  "offset": 0,
  "count": 1,
  "total_count": 1,
  "has_more": false,
  "emails": [
    {
      "id": "cf-admin-123",
      "from": "sender@example.com",
      "to": "user@googlemail.com",
      "subject": "Verification code",
      "body_preview": "Your code is 123456",
      "date": 1770000000,
      "timestamp": 1770000000,
      "body_type": "text",
      "folder": "cloudflare"
    }
  ]
}
```

## OAuth 辅助接口

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/oauth/auth-url` | 无 | 生成 Microsoft OAuth 授权链接 |
| POST | `/api/oauth/exchange-token` | JSON: `redirected_url` | 从回调 URL 中解析 `code` 并换取 Refresh Token |
| POST | `/api/accounts/<account_id>/reauthorize` | JSON: `redirected_url` | 为已有 Outlook 账号重新授权并自动刷新验证 |

换取 Token 请求示例：

```json
{
  "redirected_url": "http://localhost:8080/?code=..."
}
```

注意：Microsoft 授权码通常只能使用一次。为已有账号重新授权时，应直接调用 `/api/accounts/<account_id>/reauthorize`，不要先调用 `/api/oauth/exchange-token` 预览后再重复提交同一个回调 URL。

## 设置接口

### POST `/api/settings/validate-cron`

验证 Cron 表达式，并返回下一次执行时间与未来 5 次执行时间。

#### 请求示例

```json
{
  "cron_expression": "0 */6 * * *",
  "time_zone": "America/Los_Angeles"
}
```

可选字段 `time_zone` 用于按指定 IANA 时区预览下一次执行时间；未传时使用当前系统设置中的 `app_timezone`。

### GET `/api/settings`

获取系统设置。

除数据库 `settings` 表中的原始键值外，接口还会额外整理并返回以下常用字段：

| 字段 | 说明 |
| --- | --- |
| `login_password_masked` | 登录密码掩码 |
| `external_api_key` | 当前对外 API Key |
| `duckmail_base_url` | DuckMail API 地址 |
| `duckmail_api_key` | DuckMail API Key |
| `cloudflare_worker_domain` | 旧单渠道 Cloudflare Worker 域名，主要用于升级迁移 |
| `cloudflare_email_domains` | 旧单渠道 Cloudflare 邮箱域名列表，主要用于升级迁移 |
| `cloudflare_admin_password` | 旧单渠道 Cloudflare 管理密码，主要用于升级迁移 |
| `cloudflare_ai_username_enabled` | 是否启用 Cloudflare AI 用户名生成 |
| `cloudflare_ai_username_api_url` | Cloudflare AI 用户名生成 API 地址 |
| `cloudflare_ai_username_model` | Cloudflare AI 用户名生成模型 |
| `cloudflare_ai_username_prompt` | Cloudflare AI 用户名生成提示词模板 |
| `cloudflare_ai_username_api_key_configured` | 是否已保存 Cloudflare AI API Key |
| `cloudflare_ai_username_api_key_masked` | Cloudflare AI API Key 掩码，不返回明文 |
| `app_timezone` | 当前系统时区，IANA 时区名，例如 `Asia/Shanghai` |
| `show_account_created_at` | 是否在邮箱列表展示创建时间 |
| `show_account_sort_order` | 是否在邮箱列表展示自定义排序值 |
| `active_skin_id` | 当前实际生效皮肤 ID；配置不可用时会返回 `classic` |
| `configured_skin_id` | 当前保存的皮肤 ID；可能因为皮肤不可用而与 `active_skin_id` 不同 |
| `active_skin` | 当前实际生效皮肤对象 |
| `active_skin_asset_hash` | 当前皮肤 CSS 资源版本，用于刷新 `/assets/active-skin.css` |
| `forward_channels` | 当前启用的转发渠道 |
| `forward_check_interval_seconds` | 转发轮询间隔秒数 |
| `forward_check_interval_minutes` | 兼容旧客户端的转发检查间隔分钟数 |
| `forward_execution_mode` | 转发执行模式，`serial` 或 `parallel` |
| `forward_parallel_workers` | 并行模式 worker 数 |
| `forward_account_delay_seconds` | 串行模式下账号间隔秒数；并行模式返回 `0` |
| `forward_email_window_minutes` | 转发时间窗口 |
| `forward_include_junkemail` | 是否转发垃圾箱 |
| `email_forward_recipient` | SMTP 转发收件人 |
| `smtp_host` | SMTP 主机 |
| `smtp_port` | SMTP 端口 |
| `smtp_username` | SMTP 用户名 |
| `smtp_password` | SMTP 密码 |
| `smtp_from_email` | SMTP 发件邮箱 |
| `smtp_provider` | SMTP 类型 |
| `smtp_use_tls` | 是否启用 TLS |
| `smtp_use_ssl` | 是否启用 SSL |
| `telegram_bot_token` | Telegram Bot Token |
| `telegram_chat_id` | Telegram Chat ID |
| `normal_mail_local_retention_enabled` | 是否启用普通邮箱本地保留 |

### PUT `/api/settings`

更新系统设置。当前实现支持的主要可写字段如下。

#### 基础与调度相关字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `login_password` | string | 登录密码，至少 8 位 |
| `gptmail_api_key` | string | GPTMail API Key |
| `refresh_interval_days` | int | 刷新周期，范围 `1-90` |
| `refresh_delay_seconds` | int | 刷新间隔秒数，范围 `0-60` |
| `refresh_cron` | string | Cron 表达式 |
| `use_cron_schedule` | bool | 是否使用 Cron 调度 |
| `enable_scheduled_refresh` | bool | 是否开启定时刷新 |
| `app_timezone` | string | 系统时区，使用 IANA 时区名，例如 `Asia/Shanghai` |
| `show_account_created_at` | bool | 是否在邮箱列表展示创建时间 |
| `show_account_sort_order` | bool | 是否在邮箱列表展示自定义排序值 |
| `active_skin_id` | string | 当前系统级外观皮肤 ID；所有登录设备共用同一设置 |
| `external_api_key` | string | 对外 API Key，可传空字符串清空 |
| `normal_mail_local_retention_enabled` | bool/string | 是否启用普通邮箱本地保留；通过 `/api/settings` 更新会同步刷新后端进程内读取缓存 |

#### 临时邮箱服务相关字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `duckmail_base_url` | string | DuckMail API 地址 |
| `duckmail_api_key` | string | DuckMail API Key |
| `cloudflare_worker_domain` | string | 旧单渠道 Cloudflare Worker 域名；新配置请使用 `/api/cloudflare/channels` |
| `cloudflare_email_domains` | string | 旧单渠道 Cloudflare 邮箱域名；新配置请使用 `/api/cloudflare/channels` |
| `cloudflare_admin_password` | string | 旧单渠道 Cloudflare 管理密码；新配置请使用 `/api/cloudflare/channels` |
| `cloudflare_ai_username_enabled` | bool/string | 是否启用 Cloudflare AI 用户名生成 |
| `cloudflare_ai_username_api_url` | string | OpenAI-compatible API 地址 |
| `cloudflare_ai_username_model` | string | 模型名称 |
| `cloudflare_ai_username_prompt` | string | 提示词模板，支持 `{count}` 和 `{seed}` |
| `cloudflare_ai_username_api_key` | string | AI API Key；非空时加密保存，空字符串会保留已有值 |
| `cloudflare_ai_username_clear_api_key` | bool | 传 `true` 时清空已保存的 AI API Key |

#### 转发与 SMTP / Telegram 相关字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `forward_check_interval_seconds` | int | 轮询间隔秒数，范围 `20-3600` |
| `forward_check_interval_minutes` | int | 兼容旧客户端的轮询间隔分钟数，范围 `1-60`；未同时传 seconds 时会同步写入秒级配置 |
| `forward_execution_mode` | string | `serial` 或 `parallel`；保存为 `parallel` 时账号间隔会归零 |
| `forward_parallel_workers` | int | 并行模式 worker 数，范围 `1-10` |
| `forward_account_delay_seconds` | int | 串行模式下账号间隔，范围 `0-60`；并行模式会保存为 `0` |
| `forward_email_window_minutes` | int | 转发邮件时间范围，范围 `0-10080`，`0` 表示不限制 |
| `forward_include_junkemail` | bool | 是否把垃圾箱邮件也纳入转发轮询 |
| `forward_channels` | array<string> | `smtp` / `telegram` / `wecom` |
| `email_forward_recipient` | string | SMTP 转发收件人 |
| `smtp_host` | string | SMTP 主机 |
| `smtp_port` | int | SMTP 端口 |
| `smtp_username` | string | SMTP 用户名 |
| `smtp_password` | string | SMTP 密码 |
| `smtp_from_email` | string | SMTP 发件邮箱 |
| `smtp_provider` | string | `outlook`、`qq`、`163`、`126`、`yahoo`、`aliyun`、`custom` |
| `smtp_use_tls` | bool | 是否启用 TLS |
| `smtp_use_ssl` | bool | 是否启用 SSL |
| `telegram_bot_token` | string | Telegram Bot Token |
| `telegram_chat_id` | string | Telegram Chat ID |

#### 请求示例

```json
{
  "forward_check_interval_seconds": 20,
  "forward_execution_mode": "parallel",
  "forward_parallel_workers": 4,
  "forward_account_delay_seconds": 0,
  "forward_email_window_minutes": 30,
  "forward_include_junkemail": true,
  "smtp_provider": "outlook",
  "forward_channels": ["smtp", "telegram"]
}
```

### GET `/api/skins`

获取系统级外观皮肤列表、当前配置值和当前实际生效皮肤。该接口要求已登录。

成功响应示例：

```json
{
  "success": true,
  "configured_skin_id": "midnight-sample",
  "active_skin_id": "midnight-sample",
  "asset_hash": "a1b2c3d4e5f6a7b8",
  "active_skin": {
    "id": "midnight-sample",
    "name": "Midnight Sample",
    "version": "1.0.0",
    "source_type": "upload",
    "builtin": false,
    "active": true,
    "status": "ok",
    "asset_hash": "a1b2c3d4e5f6a7b8",
    "last_error": ""
  },
  "skins": []
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `configured_skin_id` | `settings` 表中保存的皮肤 ID |
| `active_skin_id` | 当前实际生效的皮肤 ID；配置不可用时会回退为 `classic` |
| `asset_hash` | 当前皮肤 CSS 版本，可作为 `/assets/active-skin.css?v=...` 参数 |
| `skins` | 已安装皮肤列表，始终包含内置 `classic` |

皮肤对象常见字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 皮肤 ID |
| `name` | 显示名称 |
| `version` | 版本 |
| `description` | 描述 |
| `source_type` | `builtin`、`upload` 或 `git` |
| `builtin` | 是否内置皮肤 |
| `active` | 是否当前实际生效 |
| `status` | `ok` 或 `invalid` |
| `last_error` | 最近一次校验或读取错误 |
| `git_url` | Git 来源地址，仅 Git 来源皮肤返回 |
| `git_ref` | Git ref，仅 Git 来源皮肤返回 |

### POST `/api/skins/<skin_id>/activate`

启用指定皮肤。该设置是系统级设置，保存后所有登录设备都会使用同一当前皮肤。

成功响应示例：

```json
{
  "success": true,
  "message": "皮肤已启用",
  "active_skin": {
    "id": "classic",
    "source_type": "builtin",
    "active": false,
    "status": "ok"
  },
  "asset_hash": "classic"
}
```

失败时常见错误：

- `皮肤 ID 无效`
- `皮肤不存在`
- `皮肤不可用`

也可以通过 `PUT /api/settings` 提交 `active_skin_id` 达到同样效果。

### POST `/api/skins/upload`

上传 zip 皮肤包。表单字段名支持 `skin` 或 `file`。

请求示例：

```bash
curl -X POST \
  -H "X-CSRFToken: <csrf-token>" \
  -b "session=<session-cookie>" \
  -F "skin=@skin.zip" \
  "http://localhost:5000/api/skins/upload"
```

成功响应示例：

```json
{
  "success": true,
  "message": "皮肤已安装",
  "skin": {
    "id": "midnight-sample",
    "name": "Midnight Sample",
    "version": "1.0.0",
    "source_type": "upload",
    "status": "ok"
  }
}
```

格式要求见 [`docs/skins.md`](skins.md)。上传失败不会改变当前启用皮肤。

### POST `/api/skins/git/install`

从 Git 仓库安装皮肤。仓库根目录必须包含 `skin.json` 和 CSS 入口文件。

请求示例：

```json
{
  "git_url": "https://github.com/user/outlook-skin.git",
  "git_ref": "main"
}
```

说明：

- `git_url` 必填。
- `git_ref` 可选，可以是分支、tag 或其他 `git clone --branch` 可解析的 ref。
- 运行环境必须安装 `git`。
- 私有仓库凭据没有专门管理入口，不建议把凭据直接写进多人可见的 URL。

成功响应与上传接口一致。安装失败不会改变当前启用皮肤。

### POST `/api/skins/<skin_id>/git/update`

更新已安装的 Git 来源皮肤。服务端会使用该皮肤保存的 `git_url` 和 `git_ref` 重新拉取，并要求更新后的 `skin.json.id` 与原皮肤 ID 一致。

成功响应示例：

```json
{
  "success": true,
  "message": "Git 皮肤已更新",
  "skin": {
    "id": "midnight-sample",
    "source_type": "git",
    "status": "ok"
  }
}
```

更新失败时不会覆盖现有皮肤文件。

### DELETE `/api/skins/<skin_id>`

删除未启用的自定义皮肤。不能删除内置 `classic`，也不能直接删除当前启用的皮肤；需要先切换到其他皮肤或 `classic`。

成功响应示例：

```json
{
  "success": true,
  "message": "皮肤已删除"
}
```

### GET `/assets/active-skin.css`

返回当前实际生效皮肤的 CSS。该资源用于页面加载，不要求 Session；配置不可用或 CSS 读取失败时返回空的 classic fallback CSS。

客户端可使用 `GET /api/skins` 或 `GET /api/settings` 返回的 `asset_hash` / `active_skin_asset_hash` 作为查询参数刷新缓存：

```txt
/assets/active-skin.css?v=<asset_hash>
```

### GET `/api/settings/normal-mail-retention/status`

获取普通邮箱本地保留统计和清理任务状态。

#### 成功响应示例

```json
{
  "success": true,
  "status": {
    "enabled": true,
    "saved_message_count": 128,
    "cached_body_count": 42,
    "estimated_retained_bytes": 1048576,
    "db_file_bytes": 5242880,
    "clear_status": {
      "state": "idle",
      "message": ""
    }
  }
}
```

`clear_status.state` 可能为 `idle`、`running`、`succeeded` 或 `failed`。统计值用于界面展示和清理决策，不是精确配额。

### POST `/api/settings/normal-mail-retention/clear`

启动后台清理任务，删除 `retained_normal_mail_messages` 中的普通邮箱本地保留数据。该接口不会自动关闭 `normal_mail_local_retention_enabled`；关闭开关由 `PUT /api/settings` 独立完成。

清理任务是进程内状态：重复请求不会启动第二个删除线程，而是返回当前 `running` 状态并带 `already_running=true`。后台删除遇到短暂 SQLite `database is locked` 会有限重试；最终结果通过 status 接口轮询。

#### 成功响应示例

```json
{
  "success": true,
  "already_running": false,
  "status": {
    "state": "running",
    "message": "正在清理普通邮箱本地保留缓存"
  }
}
```

### POST `/api/settings/test-forward-channel`

使用当前前端表单配置直接测试转发渠道，不要求先保存设置。

#### 请求示例

SMTP 测试：

```json
{
  "channel": "smtp",
  "config": {
    "smtp": {
      "recipient": "demo@example.com",
      "host": "smtp.office365.com",
      "port": 587,
      "username": "demo@example.com",
      "password": "secret",
      "from_email": "demo@example.com",
      "provider": "outlook",
      "use_tls": true,
      "use_ssl": false
    }
  }
}
```

Telegram 测试：

```json
{
  "channel": "telegram",
  "config": {
    "telegram": {
      "bot_token": "123:abc",
      "chat_id": "123456"
    }
  }
}
```

## 说明

### 代理使用

账号邮箱相关 API 当前会优先使用账号级代理配置；账号 `proxy_url`、`fallback_proxy_url_1`、`fallback_proxy_url_2` 三项全空时，才继承账号所属分组的代理配置。若当前分组未配置代理，会继续向上查找父级分组代理，直到找到有代理配置的祖先分组或到达一级分组：

- Graph token 获取
- Graph 邮件列表
- Graph 邮件详情
- Outlook OAuth IMAP token 获取
- Outlook OAuth IMAP 列表 / 详情 / 删除回退
- 密码型 IMAP 列表 / 详情
- 转发轮询抓信 / 详情抓取

### 别名冲突规则

别名保存时会校验：

- 不能与本账号主邮箱重复
- 不能与其他账号主邮箱重复
- 不能与其他账号别名重复
- 不能与临时邮箱地址冲突

### 特殊响应类型

以下接口不是普通 JSON 数据接口：

- `GET /api/accounts/refresh-all`: `text/event-stream`
- `GET /api/accounts/refresh-failed-stream`: `text/event-stream`
- `GET /api/accounts/trigger-scheduled-refresh`: `text/event-stream`
- `GET /api/groups/<group_id>/export`: `text/plain` 文件下载
- `GET /api/accounts/export`: `text/plain` 文件下载
- `POST /api/accounts/export-selected`: `text/plain` 文件下载
