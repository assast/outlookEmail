## ADDED Requirements

### Requirement: Cloudflare AI username settings
系统 SHALL 支持已登录用户管理 Cloudflare 临时邮箱 AI 用户名生成配置。

#### Scenario: 保存 AI 用户名配置
- **WHEN** 已登录用户提交 AI 启用状态、API 地址、模型、API Key 和用户名提示词模板
- **THEN** 系统 SHALL 保存这些设置，并 SHALL 加密保存 API Key。

#### Scenario: 读取 AI 用户名配置
- **WHEN** 已登录用户读取系统设置
- **THEN** 系统 SHALL 返回 AI 启用状态、API 地址、模型、提示词模板和 API Key 是否已配置，而 SHALL NOT 返回完整 API Key 明文。

#### Scenario: 保留已保存 API Key
- **WHEN** 已登录用户更新 AI 用户名配置但未提交新的 API Key
- **THEN** 系统 SHALL 保留已保存的 AI API Key。

#### Scenario: 清空 AI API Key
- **WHEN** 已登录用户明确请求清空 AI API Key
- **THEN** 系统 SHALL 删除已保存的 AI API Key，并在后续读取设置时报告 API Key 未配置。

### Requirement: Cloudflare AI username testing
系统 SHALL 支持已登录用户在保存或使用前测试 AI 用户名生成配置。

#### Scenario: 测试生成用户名成功
- **WHEN** 已登录用户提交完整有效的 AI 用户名配置并请求测试生成
- **THEN** 系统 SHALL 调用配置的 OpenAI-compatible API，返回清洗后的用户名列表，并 SHALL NOT 创建任何 Cloudflare 临时邮箱。

#### Scenario: 测试生成配置缺失
- **WHEN** 已登录用户请求测试生成，但 AI API 地址、模型或 API Key 缺失
- **THEN** 系统 SHALL 拒绝测试请求，并说明缺失的配置项。

#### Scenario: 测试生成上游失败
- **WHEN** AI 用户名测试生成的上游请求失败、超时或返回不可解析内容
- **THEN** 系统 SHALL 返回失败响应，并保留可理解的错误信息。

### Requirement: Cloudflare AI username generation
系统 SHALL 在 Cloudflare 批量创建临时邮箱时按配置使用 AI 生成用户名，并在 AI 不可用时安全回退。

#### Scenario: 批量创建使用 AI 用户名
- **WHEN** 已登录用户批量创建 Cloudflare 临时邮箱，AI 用户名生成已启用且配置完整
- **THEN** 系统 SHALL 请求 AI 生成不少于本次创建数量的候选用户名，并 SHALL 优先使用通过清洗和去重的候选用户名创建 Cloudflare 地址。

#### Scenario: AI 用户名提示词变量
- **WHEN** 系统请求 AI 生成 Cloudflare 用户名
- **THEN** 系统 SHALL 将提示词模板中的 `{count}` 替换为目标数量，并 SHALL 将 `{seed}` 替换为本次请求的随机种子或稳定种子文本。

#### Scenario: AI 用户名清洗
- **WHEN** AI 返回用户名候选列表
- **THEN** 系统 SHALL 对候选用户名执行小写化、去除邮箱域名、移除不允许字符、长度校验和去重，并 SHALL 只使用符合 Cloudflare 创建接口要求的用户名。

#### Scenario: AI 返回数量不足
- **WHEN** AI 返回的可用用户名数量少于本次 Cloudflare 批量创建数量
- **THEN** 系统 SHALL 使用可用 AI 用户名创建对应数量的邮箱，并 SHALL 对剩余数量回退到随机用户名生成。

#### Scenario: AI 生成失败回退
- **WHEN** Cloudflare 批量创建时 AI 配置不完整、请求失败、超时或返回内容不可用
- **THEN** 系统 SHALL 自动回退到随机用户名生成，并 SHALL 在响应中标明 AI 回退已发生。

#### Scenario: 单个手填用户名优先
- **WHEN** 已登录用户创建单个 Cloudflare 临时邮箱并手动填写用户名
- **THEN** 系统 SHALL 使用手填用户名，并 SHALL NOT 调用 AI 用户名生成。
