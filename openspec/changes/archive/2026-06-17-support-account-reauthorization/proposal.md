## Why

当前 Outlook 账号的 Refresh Token 失效后，用户只能手动获取新 Token，再进入编辑账号弹窗粘贴 `Client ID` 和 `Refresh Token`，流程容易误改账号其他字段，也会让旧的“刷新失败”状态继续干扰判断。

需要为已有 Outlook 账号提供明确的重新授权入口：授权成功后更新授权信息，清理旧失败状态，并立即用一次真实的单账号刷新验证新授权是否可用。

## What Changes

- 为已有 Outlook OAuth 账号新增“重新授权”能力，用户可从账号编辑或失败提示上下文发起。
- 重新授权流程复用现有 Microsoft OAuth 授权链接和授权码换取 Refresh Token 的能力。
- 重新授权成功后，只更新目标账号的 `client_id`、`refresh_token`、`refresh_token_updated_at` 和必要的刷新状态字段，不修改邮箱、密码、分组、状态、转发、代理、备注、别名等业务字段。
- 重新授权成功后清掉旧的刷新失败状态和错误信息，随后自动触发该账号单账号刷新。
- 自动刷新完成后，以真实刷新结果写回 `last_refresh_status`、`last_refresh_at`、`last_refresh_error`；若刷新失败，界面必须显示新的失败结果，而不是隐藏失败。
- IMAP 账号不支持重新授权入口。

## Capabilities

### New Capabilities

- `account-reauthorization`: 覆盖已有 Outlook OAuth 账号的重新授权、授权信息更新、旧失败状态清理和重新授权后的自动刷新验证。

### Modified Capabilities

- 无。

## Impact

- 后端账号 API：新增或扩展已有账号授权更新接口，处理目标账号校验、OAuth code 换 token、敏感字段加密保存、刷新状态更新和单账号刷新触发。
- 前端账号管理：在 Outlook 账号编辑弹窗和刷新失败上下文提供重新授权入口，并展示授权、换取、更新、自动刷新过程状态。
- 数据库字段：复用 `accounts.refresh_token_updated_at`、`last_refresh_status`、`last_refresh_at`、`last_refresh_error`，无需新增表。
- 文档与测试：更新 API 文档，补充后端接口测试与前端流程覆盖，重点验证不会误改账号非授权字段。
