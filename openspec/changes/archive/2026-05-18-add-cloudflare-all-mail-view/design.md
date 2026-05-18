## 背景

本项目已经在临时邮箱区域支持 GPTMail、DuckMail 和 Cloudflare Temp Email。当前 Cloudflare 支持的前提是用户选中了一个本地 `temp_emails` 记录，然后系统使用该记录保存的 JWT 调用 `/api/mails` 读取单个地址的邮件。Worker 域名、邮箱域名和管理员密码目前都是全局设置。

Cloudflare Temp Email 还提供管理员邮件列表接口 `/admin/mails`，可以列出 Worker 邮件池，并支持可选的 `address` 过滤。该接口使用管理员密码，而不是单个地址的 JWT，因此更适合作为独立的“Cloudflare 全部邮件”视图，而不是复用现有“某个临时邮箱的邮件”接口。

普通邮箱 API 已经有 plus-address 别名回退逻辑。该逻辑位于账号解析辅助函数中，并被内部和对外邮件 API 复用。

## 目标 / 非目标

**目标：**

- 为当前配置的一套 Cloudflare 渠道提供 Cloudflare Temp Email 全局邮件列表。
- 允许用户按收件地址过滤 Cloudflare 全局邮件列表。
- 查询指定地址时，如果第一个候选地址没有命中，支持 `@gmail.com` 和 `@googlemail.com` 之间互相回退。
- 保留现有 plus-address 回退行为，并让回退顺序明确且可测试。
- 返回元数据说明请求地址、实际查询或解析地址，以及是否使用了回退。
- 在可行范围内，让解析后的邮件响应字段兼容现有邮件列表和详情渲染路径。

**非目标：**

- 本次不支持多套 Cloudflare 渠道配置。
- 不修改 Cloudflare 地址创建、删除、单地址 JWT 存储语义。
- 不把 Cloudflare 全局邮件池持久化写入 `temp_email_messages`。
- 不做 `gmail.com` 和 `googlemail.com` 之外的邮箱服务商归一化。
- 不新增 Cloudflare 全局邮件附件下载能力，除非已有解析内容元数据可直接复用。

## 设计决策

### 使用独立的 Cloudflare 管理员邮件 API

新增一个后端路由承载 Cloudflare 全局视图，例如 `GET /api/cloudflare/messages`，不复用或重载 `GET /api/temp-emails/<email>/messages`。

原因：现有临时邮件路由的作用域是某个本地临时邮箱记录。管理员接口可能返回本地不存在的地址邮件，如果把它当作某个邮箱的缓存，会让数据归属变得不清晰。

备选方案：在现有临时邮箱列表中放一个特殊伪邮箱。这样可以减少 UI 入口，但会引入假的邮箱身份，并且邮件详情路由需要额外特判。

### 不把管理员列表邮件写入 `temp_email_messages`

Cloudflare 全局邮件列表应当实时获取并解析用于展示，但不写入现有临时邮件缓存表。

原因：`temp_email_messages.email_address` 绑定本地 `temp_emails.email` 外键。管理员结果可能包含 Worker 邮件池里的任意收件地址，包括没有导入到本项目的地址。

备选方案：自动创建缺失的临时邮箱记录。这样会意外改变用户的邮箱清单，并且需要定义清理语义，不属于本次需求。

### 通过 Cloudflare 响应适配器复用原始 MIME 解析

在解析原始 RFC822 内容前，先把每条 Cloudflare 管理员邮件记录中的 `id`、`message_id`、`source`、`address`、`raw`、`created_at` 等字段适配成现有展示逻辑可使用的数据形状。

原因：项目已经能解析按地址 JWT 返回的 Cloudflare 原始邮件。增加一个小型适配层，可以保持解析行为一致，同时从管理员响应中获取收件人元数据。

备选方案：依赖 Cloudflare 的 parsed mail 接口。但管理员 parsed 接口是否覆盖全局视图并不明确，而 `/admin/mails` 是已文档化的管理员列表接口。

### 集中生成地址回退候选

把当前只服务 plus-address 的辅助函数扩展为统一候选地址构建器，生成：

1. 完整归一化后的原始地址。
2. 同域名下的 plus-address 回退地址。
3. 当域名是 `gmail.com` 或 `googlemail.com` 时，为每个 plus-address 候选生成另一后缀的对应地址。

原因：账号解析和 Cloudflare 地址过滤查询都需要相同的顺序规则。集中生成可以避免不同路由各自实现后产生行为漂移。

备选方案：只在新的 Cloudflare 路由里做 Gmail 后缀回退。这样只能满足部分需求，会让 `/api/emails/<email>` 和 `/api/external/emails` 行为不一致。

### Cloudflare 地址回退以“无结果”为触发条件

对 `GET /api/cloudflare/messages?address=...`，先查询第一个候选地址。如果请求成功但返回 0 封邮件，则继续查询下一个候选地址，直到找到结果或候选地址耗尽。

原因：Cloudflare 管理员列表不解析本地账号记录，能观察到的“未找到”状态就是空结果集。这样也能让全局列表保持简单：不传 address 就不触发回退。

备选方案：总是查询两个 Gmail 后缀并合并。这样可能在 Worker 存在等价地址时产生重复，也可能违背用户对精确地址查询的预期。

## 风险 / 权衡

- Cloudflare 管理员列表可以暴露 Worker 邮件池中的所有邮件 -> 保持 session 登录鉴权，除非后续明确要求，否则不暴露到 API Key 对外接口。
- 全局邮件池较大时获取成本可能较高 -> 限制分页大小，并保留 `limit` / `offset` 语义。
- 当 offset 非 0 时，第一页为空不一定代表该过滤邮箱整体为空 -> 只在当前请求 offset 下按空结果触发回退，并通过响应元数据暴露 `fallback_used` 供调用方判断。
- Cloudflare 原始邮件响应可能随上游版本变化 -> 响应归一化应防御式实现，并保留有用的上游错误细节。
- 如果两个 Gmail 后缀都配置了账号，回退顺序可能让用户意外 -> 在响应中暴露 `requested_email`、`queried_email` 或 `resolved_email`、`fallback_used`。

## 迁移计划

- 新增辅助函数和路由，不修改现有数据库 schema。
- 保持现有按临时邮箱 JWT 获取 Cloudflare 邮件的行为不变。
- 更新文档，将新的 Cloudflare 全局列表与现有 `folder=all` 普通邮箱聚合查询分开说明。
- 回滚时移除新路由、UI 入口和 Gmail 后缀回退辅助逻辑即可，不需要数据迁移。

## 待确认问题

- Cloudflare 全局列表后续是否需要暴露到对外 API Key 接口，还是保持仅登录 session 可用？
- 第一版 UI 是否直接包含收件人过滤输入框，还是先提供路由/API 能力和简单全部邮件视图？
