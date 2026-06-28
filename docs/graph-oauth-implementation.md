# Graph Refresh Token 自动授权功能 - 实现说明

## 功能概述

已成功实现 Outlook 邮箱表格中的"去授权"按钮功能，用户可以通过纯 HTTP OAuth2 授权码流程自动提取 Microsoft Graph refresh_token，无需手动浏览器操作。

## 实现的功能

### 1. 前端界面

#### 表格增强
- ✅ 在 Outlook 邮箱表格中增加"操作"列
- ✅ 对于"未授权"的账号显示"去授权"按钮
- ✅ 已授权账号不显示按钮

#### 授权弹窗
- ✅ 点击"去授权"按钮弹出授权对话框
- ✅ 弹窗顶部显示邮箱地址和密码（密码已脱敏显示）
- ✅ 提供"授权"按钮触发授权流程
- ✅ 使用 SSE 实时日志区域显示后端授权进度和结果

### 2. 后端实现

#### 核心 OAuth 流程
文件：`outlook_web/segments/11_routes_graph_oauth.py`

实现了完整的 Microsoft OAuth2 授权码流程：

1. **获取授权页面**
   - 请求 Microsoft 授权端点
   - 提取 Flow Token (PPFT)、Post URL、Context

2. **提交登录凭据**
   - 使用邮箱和密码登录
   - 处理 JavaScript 自动提交表单

3. **处理中间页面**
   - 同意授权页面 (Consent/Update)
   - 跳过安全信息添加 (proofs/Add)
   - 通用表单处理

4. **捕获授权码**
   - 从重定向 URL 中提取授权码

5. **换取 Token**
   - 使用授权码换取 refresh_token
   - 验证 refresh_token 后写入正式账号表
   - 标记上传暂存账号为已授权

#### API 端点
- `POST /api/oauth/graph-extract-token`
  - 接收参数：`account_id`
  - 返回：`success`, `task_id`, `stream_url`

- `GET /api/oauth/graph-extract-token/<task_id>/stream`
  - 返回 SSE 事件：`start`, `log`, `success`, `error`, `complete`

### 3. 数据库更新

授权成功后自动写入正式 `accounts` 表：
- 新账号：新增正式 Outlook 账号，保存加密后的 password 和 refresh_token
- 已存在账号：更新 password、client_id、refresh_token，并清理旧刷新失败状态
- refresh_token 保存前会调用现有 `test_refresh_token()` 验证；如 Microsoft 返回 rotated refresh_token，保存 rotated 值

同时更新 `outlook_upload_accounts` 暂存表：
- `is_authorized`: 设置为 1（已授权）
- `updated_at`: 更新时间戳
- 不在暂存表保存 `client_id` 或 `refresh_token`

## 技术细节

### OAuth 配置
```python
GRAPH_EXTRACT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"  # Thunderbird public client
GRAPH_EXTRACT_REDIRECT_URI = "http://localhost"
GRAPH_EXTRACT_SCOPE = "offline_access https://graph.microsoft.com/Mail.Read"
GRAPH_EXTRACT_AUTHORITY = "consumers"
```

### 关键特性
- ✅ 纯 HTTP 实现，无需真实浏览器
- ✅ 自动处理多步重定向
- ✅ 支持同意授权页面
- ✅ 智能跳过安全信息添加
- ✅ 详细的错误信息反馈
- ✅ 使用系统代理（trust_env=True）
- ✅ 前端只传 `account_id`，邮箱和密码由后端从暂存表读取
- ✅ 使用 `log` 回调和 `session_factory` 注入，便于 mock 测试

## 文件修改清单

### 新增文件
1. `outlook_web/segments/11_routes_graph_oauth.py` - 后端 OAuth 核心逻辑

### 修改文件
1. `web_outlook_app.py`
   - 在 SEGMENT_FILES 中添加 `"11_routes_graph_oauth.py"`

2. `templates/partials/index/dialogs-management.html`
   - 表格增加"操作"列头
   - 添加 Graph OAuth 授权弹窗 HTML

3. `static/js/index/12-outlook-upload-accounts.js`
   - 修改 `renderUploadAccountsRows()` 函数，添加"去授权"按钮
   - 添加 `showGraphAuthModal()` 函数
   - 添加 `hideGraphAuthModal()` 函数
   - 添加 `appendGraphAuthLog()` 函数
   - 添加 `startGraphAuth()` 函数
   - 改为 data 属性 + 事件委托，避免 inline JS 注入
   - 改为 EventSource 消费后端 SSE 日志
   - 更新 colspan 从 7 到 8

## 使用方法

### 1. 启动应用
```bash
python web_outlook_app.py
```

### 2. 访问 Outlook 邮箱管理
1. 登录系统
2. 点击顶部导航栏"Outlook 邮箱"按钮
3. 在邮箱列表中找到"未授权"的账号

### 3. 执行授权
1. 点击"去授权"按钮
2. 确认弹窗中显示的邮箱和脱敏密码
3. 点击"授权"按钮
4. 等待 10-30 秒（实时日志会显示进度）
5. 授权成功后自动刷新列表

### 4. 查看结果
- 授权成功：状态从"未授权"变为"已授权"
- 授权失败：日志窗口显示详细错误信息

## 错误处理

### 常见错误
1. **无法提取 Flow Token**
   - 原因：Microsoft 授权页面格式变化
   - 解决：检查正则表达式是否需要更新

2. **授权流程卡住**
   - 原因：遇到未处理的中间页面
   - 解决：检查日志中的 URL，添加新的页面处理逻辑

3. **Token 换取失败**
   - 原因：授权码过期或无效
   - 解决：检查授权码提取逻辑

4. **账号密码错误**
   - 原因：用户输入的凭据不正确
   - 解决：验证账号信息

### 调试建议
- 查看浏览器控制台的网络请求
- 查看授权弹窗中的 SSE 日志
- 检查数据库中的 `accounts` 和 `outlook_upload_accounts` 表

## 安全注意事项

1. **密码传输**
   - 前端授权请求只传 `account_id`
   - 密码由后端从暂存表读取，不再回传到授权 API

2. **Token 存储**
   - refresh_token 存储在正式 `accounts` 表
   - 沿用现有加密函数保存敏感字段

3. **日志安全**
   - 前端日志对密码进行脱敏显示
   - 后端 SSE 日志不输出完整密码或完整 refresh_token

## 性能优化建议

### 当前实现
- 单账号任务使用 SSE 输出实时日志
- 适合从上传暂存表逐个授权

### 生产环境优化
1. **异步处理**
   - 使用 Celery 或 RQ 队列
   - 持久化任务状态

2. **批量授权**
   - 支持选中多个账号批量授权
   - 并发控制避免触发风控

3. **速率限制**
   - 单 IP 限流（避免 Microsoft 封禁）
   - 失败重试机制

## 后续扩展

### 可能的功能增强
1. ✨ 批量授权功能
2. ✨ Token 自动续期检测
3. ✨ 多 Client ID 轮换
4. ✨ 授权历史记录

### 已知限制
1. 当前不支持需要 MFA（多因素认证）的账号
2. 对于企业账号可能需要管理员同意
3. 当前只支持单账号授权，不支持批量并发

## 测试检查清单

- [x] 未授权账号显示"去授权"按钮
- [x] 已授权账号不显示按钮
- [x] 点击按钮弹出授权窗口
- [x] 授权窗口显示正确的邮箱和脱敏密码
- [x] 点击授权按钮触发后端请求
- [x] 日志实时显示授权进度
- [x] 授权成功后写入/更新正式账号并标记暂存账号
- [x] 授权成功后刷新列表
- [x] 授权失败显示详细错误信息
- [x] 错误处理正确反馈给用户
- [x] mock 单元测试覆盖 OAuth 状态机和路由保存行为

## 技术参考

### Microsoft OAuth 文档
- [OAuth 2.0 authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Microsoft Graph Mail API](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)

### 相关项目
- `reg-factory/extract_graph_tokens.py` - 原始实现参考
- `reg-factory/docs/graph-token-extraction-migration.md` - 迁移文档

## 维护日志

### 2026-06-29
- ✅ 初始实现完成
- ✅ 前端表格添加"去授权"按钮
- ✅ 授权弹窗和 SSE 日志显示
- ✅ 后端纯 HTTP OAuth 流程
- ✅ refresh_token 验证后保存到正式账号
- ✅ 暂存表授权状态自动更新
- ✅ 错误处理和用户反馈

## 联系与支持

如遇问题，请检查：
1. Flask 控制台日志
2. 浏览器开发者工具控制台
3. 数据库 `outlook_upload_accounts` 表状态
