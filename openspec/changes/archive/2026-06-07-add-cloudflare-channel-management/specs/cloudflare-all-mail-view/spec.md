## MODIFIED Requirements

### Requirement: Cloudflare admin global mail listing
系统 SHALL 提供一个需要登录 session 的 API，通过指定 Cloudflare 渠道或默认 Cloudflare 渠道的管理员邮件列表接口读取该渠道 Worker 邮件。

#### Scenario: 查看指定渠道全部 Cloudflare 邮件
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表且传入有效 `channel_id`，并且不传地址过滤条件
- **THEN** 系统 SHALL 调用该渠道 Worker 的管理员邮件列表接口，且不传地址过滤条件，并返回解析后的邮件列表项。

#### Scenario: 缺少 Cloudflare 渠道参数时使用默认渠道
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表，但未传入 `channel_id`
- **THEN** 系统 SHALL 使用默认 Cloudflare 渠道调用管理员邮件列表接口。

#### Scenario: Cloudflare 渠道不存在
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表，但传入的 `channel_id` 不存在
- **THEN** 系统 SHALL 返回失败响应，并说明 Cloudflare 渠道不存在。

#### Scenario: Cloudflare 渠道被禁用
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表，但传入的 `channel_id` 对应渠道已禁用
- **THEN** 系统 SHALL 返回失败响应，并说明该 Cloudflare 渠道不可用。

#### Scenario: Cloudflare 渠道配置缺失
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表，但指定渠道缺少 Worker 域名或管理员密码
- **THEN** 系统 SHALL 返回失败响应，并说明缺失的 Cloudflare 渠道配置。

#### Scenario: 上游 Cloudflare 返回错误
- **WHEN** 指定渠道的 Cloudflare 管理员邮件列表接口返回错误
- **THEN** 系统 SHALL 返回失败响应，并保留有用的上游错误细节。

### Requirement: Cloudflare admin address filtering
系统 SHALL 支持对指定 Cloudflare 渠道的全局邮件列表使用可选收件地址过滤。

#### Scenario: 按收件地址过滤指定渠道
- **WHEN** 已登录用户请求 Cloudflare 邮件并传入有效 `channel_id` 和地址过滤条件
- **THEN** 系统 SHALL 将归一化后的地址传给指定渠道的 Cloudflare 管理员邮件列表接口，并返回上游报告属于该地址的邮件。

#### Scenario: 地址过滤响应元数据
- **WHEN** Cloudflare 全局邮件查询包含地址过滤条件和有效 `channel_id`
- **THEN** 响应 SHALL 包含渠道 ID、请求地址、实际查询地址，以及是否使用了回退。

#### Scenario: 地址过滤不跨渠道回退
- **WHEN** Cloudflare 全局邮件查询包含地址过滤条件和有效 `channel_id`
- **THEN** 系统 SHALL 只在该渠道内应用地址候选回退，而 SHALL NOT 查询其他 Cloudflare 渠道。

### Requirement: Cloudflare global mail pagination
系统 SHALL 使用明确的 limit 和 offset 参数限制指定 Cloudflare 渠道的全局邮件列表请求。

#### Scenario: 分页请求
- **WHEN** 已登录用户请求 Cloudflare 全局邮件并传入有效 `channel_id`、limit 和 offset 参数
- **THEN** 系统 SHALL 将受限后的分页参数转发给指定渠道的 Cloudflare，并在响应中包含分页元数据。

#### Scenario: 超出限制的 limit
- **WHEN** 已登录用户请求超过最大允许数量的 Cloudflare 全局邮件
- **THEN** 系统 SHALL 在调用指定渠道的 Cloudflare 前将 limit 限制到配置允许的最大值。

## ADDED Requirements

### Requirement: Cloudflare channel global mail entries
系统 SHALL 为每个启用的 Cloudflare 渠道提供独立的全部邮件视图入口。

#### Scenario: 显示每个启用渠道的入口
- **WHEN** 临时邮箱列表显示 Cloudflare 提供商入口
- **THEN** 系统 SHALL 为每个启用的 Cloudflare 渠道显示一个独立的 Cloudflare 全部邮件入口，并在入口中展示渠道名称。

#### Scenario: 不显示禁用渠道入口
- **WHEN** 某个 Cloudflare 渠道已禁用
- **THEN** 系统 SHALL NOT 在 Cloudflare 全部邮件入口列表中展示该渠道。

#### Scenario: 点击渠道入口只加载该渠道
- **WHEN** 已登录用户点击某个 Cloudflare 渠道的全部邮件入口
- **THEN** 系统 SHALL 只请求该渠道的 Cloudflare 全局邮件列表。

#### Scenario: 不提供全部渠道聚合入口
- **WHEN** 临时邮箱列表显示 Cloudflare 全部邮件入口
- **THEN** 系统 SHALL NOT 显示或调用跨全部 Cloudflare 渠道聚合邮件的入口。
