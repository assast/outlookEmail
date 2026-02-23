# 📡 API 文档

## 对外 API（⭐ 新增）

对外 API 允许通过 API Key 直接访问邮件数据，无需登录 Web 界面。

### 配置 API Key

1. 登录 Web 界面，点击「⚙️ 设置」
2. 在「对外 API Key」处点击「🔑 随机生成」或手动输入
3. 点击「保存设置」

### GET /api/external/emails

通过 API Key 获取指定邮箱的邮件列表。

**认证方式：**
- Header: `X-API-Key: your-api-key`
- 或查询参数: `?api_key=your-api-key`

**查询参数：**

| 参数 | 类型 | 必填 | 说明 | 默认值 |
|------|------|------|------|--------|
| `email` | string | ✅ | 邮箱地址 | - |
| `folder` | string | ❌ | 邮件文件夹：`inbox`（收件箱）、`junkemail`（垃圾邮件） | `inbox` |
| `skip` | int | ❌ | 跳过的邮件数（分页用） | `0` |
| `top` | int | ❌ | 返回的邮件数（最大 50） | `20` |

**请求示例：**

```bash
# 获取收件箱邮件（Header 认证）
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox"

# 获取垃圾邮件（Header 认证）
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=junkemail"

# 获取收件箱邮件（查询参数认证）
curl "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox&api_key=your-api-key"

# 获取垃圾邮件（查询参数认证）
curl "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=junkemail&api_key=your-api-key"

# 分页获取
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&skip=20&top=10"
```

**成功响应：**

```json
{
  "success": true,
  "emails": [
    {
      "id": "AAMk...",
      "subject": "邮件主题",
      "from": "sender@example.com",
      "date": "2026-02-23T15:30:00Z",
      "is_read": false,
      "has_attachments": false,
      "body_preview": "邮件预览内容..."
    }
  ],
  "method": "Graph API",
  "has_more": true
}
```

**错误响应：**

```json
// 401 - 缺少或无效的 API Key
{ "success": false, "error": "缺少 API Key，请在 Header 中提供 X-API-Key" }
{ "success": false, "error": "API Key 无效" }

// 403 - 未配置 API Key
{ "success": false, "error": "未配置对外 API Key，请在系统设置中配置" }

// 400 - 参数错误
{ "success": false, "error": "缺少 email 参数" }
{ "success": false, "error": "folder 参数无效，支持: inbox, junkemail" }

// 404 - 邮箱不存在
{ "success": false, "error": "邮箱账号不存在" }
```

---

## 内部 API（需登录认证）

以下 API 需要通过 Web 界面登录后使用。

### 认证相关

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/login` | 登录页面 |
| POST | `/login` | 登录验证 |
| GET | `/logout` | 退出登录 |

### 分组管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/groups` | 获取所有分组 |
| GET | `/api/groups/<id>` | 获取单个分组 |
| POST | `/api/groups` | 创建分组 |
| PUT | `/api/groups/<id>` | 更新分组 |
| DELETE | `/api/groups/<id>` | 删除分组 |
| GET | `/api/groups/<id>/export` | 导出分组账号 |

### 账号管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/accounts` | 获取所有账号 |
| GET | `/api/accounts/<id>` | 获取单个账号 |
| POST | `/api/accounts` | 添加账号 |
| PUT | `/api/accounts/<id>` | 更新账号 |
| DELETE | `/api/accounts/<id>` | 删除账号 |
| GET | `/api/accounts/export` | 导出所有账号 |
| POST | `/api/accounts/export-selected` | 导出选中分组账号 |

### Token 刷新管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/accounts/refresh-all` | 全量刷新所有账号（流式响应） |
| POST | `/api/accounts/<id>/refresh` | 刷新单个账号 |
| POST | `/api/accounts/refresh-failed` | 重试所有失败的账号 |
| POST | `/api/accounts/<id>/retry-refresh` | 重试单个账号 |
| GET | `/api/accounts/refresh-logs` | 获取刷新历史 |
| GET | `/api/accounts/<id>/refresh-logs` | 获取单个账号的刷新历史 |
| GET | `/api/accounts/refresh-logs/failed` | 获取失败的刷新记录 |
| GET | `/api/accounts/refresh-stats` | 获取刷新统计信息 |

### 邮件操作

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/emails/<email>` | 获取邮件列表 |
| GET | `/api/email/<email>/<message_id>` | 获取邮件详情 |
| POST | `/api/emails/delete` | 批量删除邮件 |

### 临时邮箱

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/temp-emails` | 获取所有临时邮箱 |
| POST | `/api/temp-emails/generate` | 生成临时邮箱 |
| DELETE | `/api/temp-emails/<email>` | 删除临时邮箱 |
| GET | `/api/temp-emails/<email>/messages` | 获取临时邮箱邮件 |
| GET | `/api/temp-emails/<email>/messages/<id>` | 获取临时邮件详情 |
| DELETE | `/api/temp-emails/<email>/messages/<id>` | 删除临时邮件 |
| DELETE | `/api/temp-emails/<email>/clear` | 清空临时邮箱 |
| POST | `/api/temp-emails/<email>/refresh` | 刷新临时邮箱 |

### OAuth2 助手

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/oauth/auth-url` | 生成授权 URL |
| POST | `/api/oauth/exchange-token` | 换取 Refresh Token |

### 系统设置

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取所有设置 |
| PUT | `/api/settings` | 更新设置 |

---

## API 调用优先级与代理说明

### API 调用优先级

本工具在获取邮件、刷新 Token、删除邮件时，会按以下优先级自动尝试并回退：

| 优先级 | 方式 | 说明 |
|--------|------|------|
| 1️⃣ | **Graph API** | 推荐方式，功能最完整 |
| 2️⃣ | **IMAP（新服务器）** | `outlook.live.com`，Graph 失败后回退 |
| 3️⃣ | **IMAP（旧服务器）** | `outlook.office365.com`，最后尝试 |

> [!NOTE]
> 如果 Graph API 失败原因是**代理连接错误**（ProxyError），则不会继续回退 IMAP，因为代理问题与 API 方式无关。

### 分组代理支持

每个分组可配置 HTTP 或 SOCKS5 代理，分组下所有邮箱在以下操作时会走该代理：

- ✅ 获取邮件（Graph API）
- ✅ 查看邮件详情（Graph API）
- ✅ 刷新 Token
- ✅ 删除邮件（Graph API）

**代理格式示例：**
```
http://127.0.0.1:7890
socks5://127.0.0.1:7891
socks5://user:pass@proxy.example.com:1080
```

> [!IMPORTANT]
> **仅 Graph API 请求支持走代理**，IMAP 连接目前不支持代理。

> [!WARNING]
> 使用 SOCKS5 代理需要安装 `pysocks` 依赖（`pip install pysocks` 或 `pip install requests[socks]`），Docker 镜像已内置。
