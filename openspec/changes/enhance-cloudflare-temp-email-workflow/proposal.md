## Why

Cloudflare 临时邮箱当前更适合单个创建和按文本导入，批量生产账号前缀、导入时绑定渠道/标签、以及生成更自然的邮箱用户名都需要用户手工处理。把这些能力整合到现有 Cloudflare 临时邮箱流程中，可以减少批量注册场景下的重复操作，并降低导入后再手动整理标签和渠道的成本。

## What Changes

- Cloudflare 临时邮箱生成支持输入数量，按所选 Cloudflare 渠道和域名批量创建邮箱。
- Cloudflare 批量生成支持选择标签，创建成功的临时邮箱会自动绑定所选标签。
- Cloudflare 临时邮箱导入界面的格式提示和示例展示渠道文本写法，包括 `[cloudflare:<channel_name>]` 分段和 `email----jwt----channel_name` 行格式。
- Cloudflare 临时邮箱导入支持选择标签，导入新增或更新成功的临时邮箱会自动绑定所选标签。
- 新增 Cloudflare 临时邮箱 AI 用户名生成设置，支持配置 OpenAI-compatible API 地址、模型、API Key、提示词模板、启用开关和测试生成。
- Cloudflare 批量生成在启用 AI 且配置完整时优先使用 AI 生成用户名；AI 失败或结果不可用时回退到现有随机用户名生成。

## Capabilities

### New Capabilities

- `cloudflare-temp-email-ai-usernames`: 管理 Cloudflare 临时邮箱用户名的 AI 增强生成配置、测试生成和失败回退规则。

### Modified Capabilities

- `cloudflare-channel-management`: 扩展 Cloudflare 临时邮箱创建和导入要求，支持批量生成、导入渠道文本示例和标签自动绑定。

## Impact

- 后端 API：新增或扩展 Cloudflare 临时邮箱批量生成、导入和 AI 用户名测试接口。
- 数据存储：复用现有 `settings` 保存 AI 配置，API Key 使用已有加密设置能力；复用 `temp_email_tags` 保存临时邮箱标签关系。
- 前端 UI：更新临时邮箱生成弹窗、导入账号弹窗和 Cloudflare 设置区。
- 外部依赖：不新增 Python SDK，AI 调用使用现有 `requests` 访问 OpenAI-compatible HTTP API。
- 测试：补充 Cloudflare 批量生成、导入渠道/标签、AI 用户名清洗与回退的后端测试，并覆盖关键前端行为。
