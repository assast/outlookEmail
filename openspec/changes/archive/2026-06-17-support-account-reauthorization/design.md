## Context

OutlookEmail 当前已有两个相关能力：

- OAuth 助手：`/api/oauth/auth-url` 生成 Microsoft 授权链接，`/api/oauth/exchange-token` 使用回调 URL 换取 `refresh_token` 和系统配置的 `client_id`。
- Token 刷新：单账号刷新会使用账号保存的 `client_id` / `refresh_token` 换取访问令牌，并把真实刷新结果写入 `last_refresh_status`、`last_refresh_at`、`last_refresh_error`；当 Microsoft 返回轮换后的 refresh token 时，会更新 `refresh_token_updated_at`。

现有账号编辑接口可以更新 `client_id` / `refresh_token`，但这是完整账号编辑流程，容易把授权更新和邮箱、分组、代理、别名等无关字段混在一起。重新授权需要成为目标明确的窄流程。

## Goals / Non-Goals

**Goals:**

- 为已有 Outlook OAuth 账号提供重新授权入口。
- 重新授权只更新目标账号的授权字段和必要刷新状态，不误改账号业务配置。
- 重新授权成功后立即清理旧刷新失败状态，并自动触发单账号刷新验证新授权。
- 自动刷新以真实结果落库：成功显示成功，失败显示新的失败错误。
- 前端在编辑账号和刷新失败场景中能发起该流程，并展示处理结果。

**Non-Goals:**

- 不支持 IMAP 账号重新授权。
- 不做批量重新授权。
- 不新增 Microsoft OAuth 应用配置管理。
- 不改变现有导入账号、普通编辑账号、全量刷新调度语义。

## Decisions

### 使用账号级重新授权窄接口

新增账号级接口，例如 `POST /api/accounts/<account_id>/reauthorize`。请求体只接收授权后的回调 URL，后端负责提取 code、换取 token、更新账号授权字段、清理旧失败状态并触发单账号刷新。

理由：复用完整 `PUT /api/accounts/<account_id>` 会要求前端提交大量无关字段，风险是重新授权时误改密码、分组、状态、代理、备注或别名。窄接口把授权更新限制在后端可控范围内。

替代方案：让前端先调用 `/api/oauth/exchange-token`，再把结果塞回编辑表单并调用保存。这个实现更少，但仍依赖完整编辑提交，不适合作为失败恢复流程。

### 后端复用 OAuth 换 token 逻辑

把现有 `/api/oauth/exchange-token` 中“从 redirected_url 提取 code 并请求 Microsoft token endpoint”的逻辑抽成共享 helper。OAuth 助手和账号重新授权接口都调用该 helper。

理由：避免两套授权码解析和 token 请求逻辑漂移，也便于测试失败消息。

替代方案：重新授权接口内部复制一份换 token 逻辑。短期可行，但重复代码会增加后续 scopes、redirect URI 或错误处理调整成本。

### 授权更新与自动刷新分阶段处理

重新授权成功换到 refresh token 后，先保存新 `client_id` / `refresh_token` / `refresh_token_updated_at`，同时清理旧的 `last_refresh_status` / `last_refresh_error`，再调用现有单账号刷新逻辑。最终响应返回授权更新结果和自动刷新结果。

理由：用户明确完成了重新授权，旧失败状态已不再代表当前授权；随后自动刷新给出真实验证结论。如果自动刷新失败，失败状态会被新错误覆盖。

替代方案：只有自动刷新成功才写入新 token。这样能避免保存不可用 token，但会让用户已经完成的新授权丢失；而且自动刷新可能因代理或临时网络失败，不一定代表 token 无效。

### 不伪造刷新成功

重新授权接口可以清理旧失败状态，但不能直接把 `last_refresh_status` 写成 `success`。`success` 只能来自自动单账号刷新真实成功。

理由：刷新状态是“最近一次刷新验证”的结果，不是“最近一次授权操作”的结果。

### 前端复用授权弹窗结构但带账号上下文

前端可扩展现有 OAuth 弹窗，增加“更新已有账号”模式。该模式预填当前账号邮箱，隐藏或禁用保存新账号相关字段，并把主按钮行为切换为“更新授权并刷新”。

理由：现有弹窗已经覆盖授权链接、打开授权页、粘贴回调 URL、换取 token 的心智模型；增加模式比新建完全独立弹窗更省维护。

替代方案：在编辑账号弹窗内直接嵌入授权步骤。这样上下文更集中，但会让编辑弹窗更复杂，并和现有 OAuth 助手重复更多 UI。

## Risks / Trade-offs

- 重新授权后自动刷新可能因代理或 Microsoft 临时失败而失败 → 保存新授权后用真实刷新结果覆盖状态，并在响应中返回新的错误，不隐藏失败。
- 授权成功但账号邮箱和 Microsoft 登录邮箱不一致 → 系统目前无法可靠从 token 中确认目标邮箱；保留现状，不强制校验邮箱一致性，必要时在 UI 文案提示用户为当前账号授权。
- 清理旧失败状态和自动刷新之间存在短暂中间态 → 接口同步触发单账号刷新，前端只在完整响应后刷新列表，减少中间态暴露。
- 换 token 与刷新都涉及网络请求，接口耗时可能较长 → 复用现有请求超时和错误处理；首版保持同步流程，后续再评估异步任务。

## Migration Plan

- 无数据库迁移；复用已有 `accounts.refresh_token_updated_at` 和刷新状态字段。
- 发布后旧账号无需处理，只有用户触发重新授权时才更新授权字段。
- 如需回滚，移除前端入口和新接口即可；已保存的新 refresh token 可继续被现有刷新逻辑使用。

## Open Questions

- 是否需要在账号列表展示 `refresh_token_updated_at`，作为“最近授权更新”时间。本次首版不要求展示，避免扩大列表改动。
