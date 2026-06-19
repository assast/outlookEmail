## Context

现有临时邮箱能力集中在 `outlook_web/segments/06_routes_temp_email.py` 和 `static/js/index/03-temp-emails.js`。Cloudflare 渠道已经有独立配置表、默认渠道、按渠道生成、按渠道导入导出、以及 `temp_emails.cloudflare_channel_id` 绑定。标签系统也已经覆盖临时邮箱，使用 `temp_email_tags` 关系表和 `/api/temp-emails/tags` 批量接口。

当前缺口主要在工作流层：Cloudflare 生成仍是单个邮箱一次提交；导入虽然后端能解析 `[cloudflare:<channel_name>]` 和第三列渠道名，但界面格式示例没有把这些写法展示出来；导入临时邮箱时现有标签选择被隐藏；用户名生成只支持用户手填或随机前缀。

## Goals / Non-Goals

**Goals:**

- 让 Cloudflare 临时邮箱可以按数量批量生成，并为成功创建的邮箱自动绑定标签。
- 让 Cloudflare 临时邮箱导入通过格式提示展示渠道文本写法，并支持在导入时选择标签。
- 提供可配置的 AI 用户名生成能力，使用 OpenAI-compatible HTTP API，并在失败时自动回退随机生成。
- 复用现有数据库结构、设置表、加密能力和标签关系，减少迁移成本。

**Non-Goals:**

- 不改变 GPTMail、DuckMail 的生成规则和导入格式。
- 不引入 OpenAI SDK 或新的后台任务系统。
- 不实现跨 Cloudflare 渠道聚合创建或全局邮件聚合。
- 不把 AI 生成结果保存为独立历史记录。

## Decisions

### 后端提供 Cloudflare 批量生成接口

新增 Cloudflare 批量生成 API，接收 `count`、`channel_id`、`domain`、`tag_ids` 和可选的 AI 生成开关。后端循环调用现有 Cloudflare 创建地址逻辑，并返回成功邮箱、失败明细、成功数和失败数。

选择后端单接口而不是前端循环调用现有单个接口，原因是批量状态、标签绑定、AI 用户名列表、部分失败响应都需要同一个事务边界和统一结果格式。前端循环会把这些逻辑分散到浏览器，失败恢复和测试都更复杂。

批量数量限制为 `1-50`。这个范围能覆盖常见批量注册场景，同时避免一次请求长时间占用 Worker 和 Web 进程。实现时按顺序创建，暂不并发请求 Cloudflare 上游。

### 标签绑定复用 `temp_email_tags`

生成和导入时接收 `tag_ids`，后端先过滤出真实存在的标签 ID，再对新增或更新成功的临时邮箱执行 `INSERT OR IGNORE`。导入时标签同时应用到新增邮箱和已存在但被更新的邮箱。

这样不需要修改 `temp_emails` 表，也和现有批量打标 API 保持一致。普通账号导入当前只给新增账号打标，但临时邮箱导入在本次变更中按用户操作语义处理为“本次成功导入的结果都打标”。

### 导入渠道通过文本显式声明

Cloudflare 导入不新增渠道选择控件，渠道继续通过导入文本声明。解析每一行时优先级如下：

1. 第三列渠道名，例如 `email----jwt----cfmail-us`。
2. 当前 `[cloudflare:<channel_name>]` 分段。
3. 系统默认 Cloudflare 渠道。

这保留了现有导出文件可原样导入的能力，也避免新增一个与文本格式重复的渠道选择器。前端只需要在 Cloudflare 临时邮箱导入提示和示例中展示 `[cloudflare:<channel_name>]` 分段和 `email----jwt----channel_name` 行格式。

### AI 用户名生成使用 OpenAI-compatible HTTP

AI 配置保存到 `settings`，包括启用开关、API 地址、模型、API Key 和提示词模板。API Key 使用已有 `set_setting_encrypted/get_setting_decrypted`，GET 设置接口只返回是否已配置或掩码，不回显完整密钥。

调用方式使用现有 `requests`，不新增 SDK。接口按 OpenAI-compatible `/chat/completions` 处理，要求模型返回 JSON 数组或可提取的用户名列表。后端会清洗、去重、限制长度，并只保留 Cloudflare 用户名允许的字符。

AI 生成失败、配置不完整、返回数量不足或清洗后不可用时，不阻断创建流程；缺口部分使用现有随机用户名生成。

### 前端只在相关上下文显示新字段

生成弹窗中只在选择 Cloudflare 时显示数量、Cloudflare 渠道、域名、用户名/AI 相关状态和标签选择。GPTMail、DuckMail 保持当前单个生成体验。

导入弹窗中临时邮箱分组仍隐藏普通账号的备注、状态和转发字段，但保留标签选择；当临时邮箱提供商选择 Cloudflare 时，格式提示和示例展示渠道文本写法。

## Risks / Trade-offs

- AI API 兼容性差异 -> 请求体使用最通用的 chat completions 格式，响应解析兼容 JSON 数组、换行列表和逗号列表，失败时回退随机生成。
- 批量请求耗时较长 -> 限制最大数量为 50，并返回部分成功结果；前端按钮展示处理中状态，避免重复提交。
- AI 生成用户名可能不符合 Cloudflare 规则 -> 后端统一清洗、去重、长度限制，并在创建前再次校验。
- 导入渠道写法不明显 -> Cloudflare 导入提示和示例明确展示 `[cloudflare:<channel_name>]` 与 `email----jwt----channel_name` 两种格式。
- 设置接口回显密钥有泄露风险 -> AI API Key 不明文回显，编辑时留空表示保留原值。

## Migration Plan

该变更不需要新增数据库表。初始化时为 AI 设置写入空默认值即可；旧数据继续使用默认 Cloudflare 渠道和现有标签关系。

部署后，旧的单个生成接口、旧的 `[cloudflare]` 导入、`[cloudflare:<channel_name>]` 导入和 `email----jwt----channel` 导入都继续可用。若需要回滚，移除新增 UI 和 API 后，已创建的临时邮箱与标签关系仍是现有结构，可继续被旧代码读取。

## Open Questions

- AI 用户名默认提示词是否固定为英文公司风格，还是允许未来按场景维护多个模板。本次先提供一个可编辑模板，不做模板库。
