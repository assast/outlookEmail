## 1. 数据模型与迁移

- [x] 1.1 为 Cloudflare 渠道迁移编写测试，覆盖创建默认渠道、绑定旧 Cloudflare 临时邮箱、旧配置缺失时不创建空渠道。
- [x] 1.2 新增 `cloudflare_channels` 表，包含渠道名称、Worker 域名、邮箱域名、加密管理员密码、启用状态和默认标记。
- [x] 1.3 为 `temp_emails` 增加 `cloudflare_channel_id` 字段，并保留现有邮箱地址全局唯一约束。
- [x] 1.4 实现旧全局 Cloudflare 配置到默认渠道的幂等迁移，并为旧 Cloudflare 临时邮箱补写渠道归属。
- [x] 1.5 增加 Cloudflare 渠道查询、创建、更新、删除、默认渠道解析和引用计数辅助函数。

## 2. 后端渠道 API 与 Cloudflare 请求链路

- [x] 2.1 为 Cloudflare 渠道 CRUD、启用/禁用、删除保护和域名查询编写后端测试。
- [x] 2.2 新增需要登录 session 的 Cloudflare 渠道管理 API，支持列出、创建、更新、删除渠道。
- [x] 2.3 将 `cloudflare_temp_request` 调整为接收渠道上下文，并使用渠道 Worker 域名和解密后的管理员密码发起请求。
- [x] 2.4 更新 Cloudflare 域名列表 API，使其按 `channel_id` 返回对应渠道域名，并拒绝不存在或禁用渠道。
- [x] 2.5 更新 Cloudflare 临时邮箱创建逻辑，要求选择有效启用渠道，并将新邮箱绑定到该渠道。
- [x] 2.6 更新 Cloudflare 单邮箱读信和删除上游地址逻辑，使其使用邮箱所属渠道。

## 3. Cloudflare 全部邮件视图

- [x] 3.1 为 `/api/cloudflare/messages` 的默认渠道回退、渠道不存在、渠道禁用、地址过滤不跨渠道回退编写测试。
- [x] 3.2 更新 `/api/cloudflare/messages`，要求传入 `channel_id` 并只查询指定渠道的管理员邮件列表。
- [x] 3.3 在 Cloudflare 全局邮件响应中返回渠道元数据，并保留请求地址、实际查询地址、分页和回退元数据。
- [x] 3.4 确认 Cloudflare 全局邮件仍不写入 `temp_email_messages`，并保留原始 MIME 归一化行为。

## 4. 导入导出兼容

- [x] 4.1 为 `[cloudflare:<channel_name>]` 分段导入、旧 `[cloudflare]` 导入、旧 `email----jwt` 导入和不存在渠道错误编写测试。
- [x] 4.2 更新临时邮箱导入解析，支持按 Cloudflare 渠道分段导入，并让旧格式落到默认渠道。
- [x] 4.3 更新已有 Cloudflare 邮箱导入更新逻辑，使其更新 JWT 和渠道归属而不创建重复邮箱记录。
- [x] 4.4 更新分组导出和全部分组导出，使 Cloudflare 临时邮箱按 `[cloudflare:<channel_name>]` 分段输出。

## 5. 前端交互

- [x] 5.1 在设置页新增 Cloudflare 渠道管理界面，支持新增、编辑、启用/禁用和删除渠道，并展示删除被引用渠道时的错误。
- [x] 5.2 更新生成临时邮箱弹窗，Cloudflare 模式下先选择渠道，再加载该渠道域名列表。
- [x] 5.3 更新临时邮箱列表，展示 Cloudflare 邮箱所属渠道，并为每个启用渠道渲染独立的 `Cloudflare所有邮件 · <channel>` 入口。
- [x] 5.4 更新 Cloudflare 全部邮件前端状态和请求参数，使筛选、分页、刷新都携带当前 `channel_id`。
- [x] 5.5 移除或兼容旧单入口 Cloudflare 全部邮件前端状态，避免不同渠道共享错误的地址过滤状态。

## 6. 文档与验证

- [x] 6.1 更新 README 和 API 文档，说明多 Cloudflare 渠道配置、创建邮箱、全部邮件视图和导入导出格式。
- [x] 6.2 运行相关后端单元测试，至少覆盖迁移、渠道 API、Cloudflare 创建/读取/删除、全局邮件和导入导出。
- [x] 6.3 运行前端静态/构建验证或项目现有 smoke 测试，确认设置页、生成弹窗和临时邮箱列表没有语法错误。
- [x] 6.4 手动验证旧单渠道配置升级路径：旧配置启动后自动出现默认渠道，已有 Cloudflare 临时邮箱可继续读信和删除。
