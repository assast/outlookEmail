## Why

当前 Cloudflare Temp Email 只支持一套全局 Worker 域名、可选邮箱域名和管理员密码配置。用户已经部署了多个 cfmail 渠道，每个渠道对应独立 Worker、管理员密码和邮件池，需要在本项目中分别创建、查看和管理这些渠道的临时邮箱。

## What Changes

- 新增 Cloudflare 渠道管理能力，支持维护多套 Cloudflare Temp Email Worker 配置。
- Cloudflare 临时邮箱创建时支持选择渠道，并只展示所选渠道的邮箱域名。
- Cloudflare 临时邮箱记录保存所属渠道，后续读取邮件和删除上游地址时使用该渠道的 Worker 与管理员密码。
- 将现有全局 Cloudflare 配置迁移为默认渠道，兼容已有配置和已有 Cloudflare 临时邮箱记录。
- Cloudflare 全部邮件视图改为按渠道查看，每个渠道提供独立入口，不提供跨渠道聚合视图。
- Cloudflare 全局邮件 API 改为需要明确渠道上下文，并只查询指定渠道的邮件池。
- Cloudflare 导入/导出格式支持携带渠道信息；旧格式导入时落到默认渠道。

## Capabilities

### New Capabilities
- `cloudflare-channel-management`: 管理多套 Cloudflare Temp Email 渠道配置，并将 Cloudflare 临时邮箱操作绑定到所属渠道。

### Modified Capabilities
- `cloudflare-all-mail-view`: Cloudflare 全部邮件列表从单一全局配置改为按指定渠道查询，且不提供全部渠道聚合。

## Impact

- 数据库：新增 Cloudflare 渠道表，并为 `temp_emails` 增加 Cloudflare 渠道归属字段；迁移旧全局配置和已有 Cloudflare 临时邮箱。
- 后端：调整 Cloudflare 请求辅助函数、渠道 CRUD API、域名列表 API、临时邮箱创建/读取/删除、导入/导出和全局邮件列表路由。
- 前端：设置页新增渠道管理；临时邮箱生成弹窗新增渠道选择；账号列表显示每个渠道的 Cloudflare 全部邮件入口和邮箱所属渠道。
- 文档与测试：更新 README/API 文档，并增加渠道迁移、创建、读取、删除、导入导出和按渠道全局邮件视图测试。
