## 1. 地址回退辅助函数

- [x] 1.1 新增共享邮箱查询候选构建器，顺序保持为完整地址优先、现有 plus-address 回退其次、Gmail/Googlemail 后缀回退最后。
- [x] 1.2 更新账号解析逻辑使用共享候选构建器，同时保留当前别名和 plus-address 行为。
- [x] 1.3 从账号解析结果返回回退元数据，让内部和对外邮件 API 可以暴露请求地址与解析地址细节。

## 2. Cloudflare 管理员邮件后端

- [x] 2.1 新增 Cloudflare 管理员邮件请求辅助函数，使用当前配置的 Worker 域名和管理员密码调用 `GET /admin/mails`。
- [x] 2.2 新增 Cloudflare 管理员邮件记录的响应归一化逻辑，包括原始 RFC822 解析、收件人元数据、稳定 ID、时间戳，以及缺少 raw 内容记录的安全处理。
- [x] 2.3 新增需要登录 session 的 Cloudflare 全局邮件路由，支持受限的 `limit`、`offset` 和可选地址过滤参数。
- [x] 2.4 仅当 Cloudflare 地址过滤查询第一次成功但返回 0 封邮件时，应用 Gmail/Googlemail 回退。
- [x] 2.5 确保 Cloudflare 全局邮件不会插入 `temp_emails` 或 `temp_email_messages`。

## 3. API 集成

- [x] 3.1 更新 `/api/emails/<email_addr>`，在账号解析使用回退候选时返回回退元数据。
- [x] 3.2 更新 `/api/external/emails`，在账号解析使用回退候选时返回回退元数据。
- [x] 3.3 保持现有按临时邮箱 Cloudflare JWT 获取邮件的行为不变。
- [x] 3.4 针对 Cloudflare Worker 域名缺失、Cloudflare 管理员密码缺失、上游 Cloudflare 管理员 API 失败返回清晰错误。

## 4. 前端

- [x] 4.1 在临时邮箱 UI 中新增 Cloudflare 全部邮件入口。
- [x] 4.2 为 Cloudflare 全部邮件视图新增收件地址过滤控件。
- [x] 4.3 渲染 Cloudflare 全局邮件行，包含收件人、发件人、主题、时间戳、预览，以及适用时的回退元数据。
- [x] 4.4 尽可能复用现有邮件详情渲染逻辑展示 Cloudflare 全局邮件。

## 5. 文档

- [x] 5.1 将 Cloudflare 全局邮件 API 与现有 `folder=all` 普通邮箱聚合查询分开记录。
- [x] 5.2 记录内部 API、对外 API 和 Cloudflare 地址过滤查询中的 Gmail/Googlemail 回退行为。
- [x] 5.3 更新 README 中面向用户的 Cloudflare 全部邮件视图说明。

## 6. 测试

- [x] 6.1 为共享邮箱查询候选顺序新增单元测试，覆盖 plus-address 与 Gmail/Googlemail 组合。
- [x] 6.2 新增账号解析测试，证明现有 plus-address 回退仍可工作，并且 Gmail/Googlemail 回退能解析另一后缀账号。
- [x] 6.3 新增不带地址过滤的 Cloudflare 全局列表后端测试。
- [x] 6.4 新增 Cloudflare 地址过滤回退后端测试，覆盖第一个后缀返回 0 封邮件、另一后缀返回邮件的场景。
- [x] 6.5 新增后端测试，证明 Cloudflare 全局列表不会写入 `temp_emails` 或 `temp_email_messages`。
- [x] 6.6 运行覆盖邮件 API、临时邮箱和 IMAP 文件夹解析行为的聚焦测试套件。
