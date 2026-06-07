## Context

项目当前把 Cloudflare Temp Email 视为一套全局配置：`cloudflare_worker_domain`、`cloudflare_email_domains` 和 `cloudflare_admin_password` 存在 `settings` 表中。所有 Cloudflare 创建地址、删除地址、按 JWT 读取单地址邮件，以及 `/api/cloudflare/messages` 管理员全局邮件列表都会读取这套全局配置。

用户现在有多个 cfmail 渠道。每个渠道有独立 Worker、管理员密码、可选邮箱域名和邮件池；不同渠道不会出现完全相同的邮箱地址；不需要跨渠道聚合的全部邮件视图。

## Goals / Non-Goals

**Goals:**
- 支持维护多套 Cloudflare Temp Email 渠道配置。
- 让 Cloudflare 临时邮箱创建、读取、删除都使用邮箱所属渠道。
- 让 Cloudflare 全部邮件视图按单个渠道查看。
- 保留 `temp_emails.email` 全局唯一约束，避免把所有临时邮箱路由改为按 ID 操作。
- 迁移旧全局 Cloudflare 配置和已有 Cloudflare 临时邮箱到默认渠道。
- 兼容旧 Cloudflare 导入格式，并让新导出格式携带渠道信息。

**Non-Goals:**
- 不提供全部 Cloudflare 渠道聚合邮件视图。
- 不支持不同渠道中存在完全相同的邮箱地址。
- 不修改 GPTMail、DuckMail 或普通邮箱的管理语义。
- 不新增 Cloudflare 全局邮件持久化缓存。
- 不改变 Cloudflare Worker 上游 API 协议。

## Decisions

### 新增 `cloudflare_channels` 表

新增表保存多套渠道配置：

```text
cloudflare_channels
  id INTEGER PRIMARY KEY
  name TEXT UNIQUE NOT NULL
  worker_domain TEXT NOT NULL
  email_domains TEXT DEFAULT ''
  admin_password TEXT NOT NULL
  enabled INTEGER DEFAULT 1
  is_default INTEGER DEFAULT 0
  created_at TIMESTAMP
  updated_at TIMESTAMP
```

`email_domains` 非必填，可为空字符串，表示该渠道暂不配置可创建邮箱的域名；渠道名称通过 `LOWER(name)` 唯一索引保证大小写不敏感唯一；`admin_password` 使用现有 `encrypt_data` / `decrypt_data` 加密存储。旧 `settings.cloudflare_admin_password` 仍可保留用于回滚和迁移判断，但新请求路径应优先读取渠道表。

备选方案是在 `settings` 里保存 JSON 数组。这样迁移少，但设置更新、默认渠道约束、按渠道查询、删除保护和测试都会变差。

### 为 `temp_emails` 增加渠道归属字段

新增 `temp_emails.cloudflare_channel_id`。Cloudflare 邮箱创建、导入和旧数据迁移时写入该字段；非 Cloudflare 提供商保持 `NULL`。

因为用户确认不同渠道不会有相同邮箱地址，继续保留 `email TEXT UNIQUE NOT NULL`。这能复用现有按邮箱地址选择、读取、删除的路由，减少前端和 API 改动。

备选方案是把临时邮箱路由全部改为按 `temp_email_id` 操作。它能支持跨渠道重复地址，但本次不是需求，会扩大改动面。

### Cloudflare 请求辅助函数接收渠道上下文

将 Cloudflare 请求从“内部读取全局设置”调整为“接收渠道对象或渠道 ID 后组装请求”。调用方负责解析渠道：

- 生成地址：使用用户选择的渠道。
- 单地址邮件：从 `temp_emails.cloudflare_channel_id` 读取渠道。
- 删除地址：从待删除邮箱记录读取渠道。
- 全部邮件列表：从 `channel_id` 查询参数读取渠道。

备选方案是引入一个全局“当前渠道”设置。这样会让多用户会话、并发请求和后台操作变得不可靠。

### 每个渠道一个 Cloudflare 全部邮件入口

临时邮箱列表中的固定入口从一个 `Cloudflare所有邮件` 改为按渠道生成多个入口，例如：

```text
Cloudflare所有邮件 · cfmail-us
Cloudflare所有邮件 · cfmail-hk
```

点击入口后前端请求 `/api/cloudflare/messages?channel_id=<id>`，不请求其他渠道。

备选方案是在进入 Cloudflare 全部邮件后再用下拉框切换渠道。入口列表更直接，也更符合“不做聚合”的范围。

### 导入导出使用渠道分段格式

Cloudflare 新导出格式按渠道分段：

```text
[cloudflare:cfmail-us]
user@example.com----jwt
```

旧格式继续支持：

```text
[cloudflare]
user@example.com----jwt
```

旧格式导入时写入默认 Cloudflare 渠道。导入遇到不存在的渠道名时返回可理解错误，不自动创建渠道。

备选方案是在每行追加 `----channel_name`。这种格式对批量导出不如分段清晰，但可以作为兼容输入支持。

### 有引用的渠道不能删除

如果某个渠道仍被 Cloudflare 临时邮箱引用，系统拒绝删除该渠道。用户可以禁用渠道，禁用后不可用于新建邮箱或查看全部邮件，但已存在邮箱仍保留归属信息，便于后续重新启用或迁移。

备选方案是删除渠道时同时删除本地邮箱或把邮箱移动到默认渠道。前者破坏性太强，后者会让邮箱的上游 Worker 归属错误。

## Risks / Trade-offs

- [迁移遗漏旧 Cloudflare 邮箱] → 迁移时为所有 `provider='cloudflare'` 且 `cloudflare_channel_id IS NULL` 的记录写入默认渠道，并增加回归测试。
- [用户删除或禁用渠道后已有邮箱无法读信] → 禁用只阻止新建和全局视图，不清空已有归属；删除前检查引用。
- [管理员密码加密迁移失败] → 迁移失败时不创建半成品渠道，保留旧 settings 值，前端继续提示缺失渠道配置。
- [导入格式歧义] → 优先解析 `[cloudflare:<channel>]` 分段；旧 `[cloudflare]` 使用默认渠道；行内渠道只作为补充兼容。
- [旧 `/api/cloudflare/messages` 调用缺少渠道] → 返回明确错误并提示需要 `channel_id`，前端所有入口都传渠道。

## Migration Plan

1. 创建 `cloudflare_channels` 表。
2. 为 `temp_emails` 增加 `cloudflare_channel_id`。
3. 如果旧全局 Cloudflare Worker 域名和管理员密码存在且渠道表为空，创建默认渠道，名称可为 `default` 或 `Cloudflare 默认`；旧邮箱域名配置可为空。
4. 将已有 Cloudflare 临时邮箱绑定到默认渠道。
5. 更新请求路径、前端入口和导入导出。
6. 回滚时可以继续保留新表和字段；旧全局 settings 未删除，因此旧版本仍能读取原全局配置，但新渠道数据不会被旧版本理解。

## Open Questions

- 默认渠道名称使用 `default` 还是中文展示名，需要在实现时结合现有 UI 文案确认。
