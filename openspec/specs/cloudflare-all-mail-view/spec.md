# cloudflare-all-mail-view Specification

## Purpose
TBD - created by archiving change add-cloudflare-all-mail-view. Update Purpose after archive.
## Requirements
### Requirement: Cloudflare admin global mail listing
系统 SHALL 提供一个需要登录 session 的 API，通过 Cloudflare 管理员邮件列表接口读取当前配置的 Cloudflare Temp Email Worker 邮件。

#### Scenario: 查看全部 Cloudflare 邮件
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表且不传地址过滤条件
- **THEN** 系统 SHALL 调用当前配置 Worker 的管理员邮件列表接口，且不传地址过滤条件，并返回解析后的邮件列表项。

#### Scenario: Cloudflare 配置缺失
- **WHEN** 已登录用户请求 Cloudflare 全局邮件列表，但 Worker 域名或管理员密码未配置
- **THEN** 系统 SHALL 返回失败响应，并说明缺失的 Cloudflare 配置。

#### Scenario: 上游 Cloudflare 返回错误
- **WHEN** Cloudflare 管理员邮件列表接口返回错误
- **THEN** 系统 SHALL 返回失败响应，并保留有用的上游错误细节。

### Requirement: Cloudflare admin address filtering
系统 SHALL 支持对 Cloudflare 全局邮件列表使用可选收件地址过滤。

#### Scenario: 按收件地址过滤
- **WHEN** 已登录用户请求 Cloudflare 邮件并传入地址过滤条件
- **THEN** 系统 SHALL 将归一化后的地址传给 Cloudflare 管理员邮件列表接口，并返回上游报告属于该地址的邮件。

#### Scenario: 地址过滤响应元数据
- **WHEN** Cloudflare 全局邮件查询包含地址过滤条件
- **THEN** 响应 SHALL 包含请求地址、实际查询地址，以及是否使用了回退。

### Requirement: Cloudflare global mail pagination
系统 SHALL 使用明确的 limit 和 offset 参数限制 Cloudflare 全局邮件列表请求。

#### Scenario: 分页请求
- **WHEN** 已登录用户请求 Cloudflare 全局邮件并传入 limit 和 offset 参数
- **THEN** 系统 SHALL 将受限后的分页参数转发给 Cloudflare，并在响应中包含分页元数据。

#### Scenario: 超出限制的 limit
- **WHEN** 已登录用户请求超过最大允许数量的 Cloudflare 全局邮件
- **THEN** 系统 SHALL 在调用 Cloudflare 前将 limit 限制到配置允许的最大值。

### Requirement: Cloudflare raw mail normalization
系统 SHALL 将 Cloudflare 管理员邮件记录归一化为现有 UI 渲染流程期望的邮件列表和详情字段。

#### Scenario: 解析原始邮件项
- **WHEN** Cloudflare 返回包含原始 RFC822 内容的邮件记录
- **THEN** 系统 SHALL 解析发件人、收件人、主题、预览文本、是否包含 HTML、时间戳和稳定邮件 ID 用于展示。

#### Scenario: 邮件项缺少原始内容
- **WHEN** Cloudflare 邮件记录缺少原始 RFC822 内容
- **THEN** 系统 SHALL 跳过该记录或安全表示该记录，且不影响整体响应。

### Requirement: Cloudflare global view isolation
系统 SHALL 保持 Cloudflare 全局邮件列表与本地临时邮箱缓存隔离。

#### Scenario: 全局邮件地址未导入本地
- **WHEN** Cloudflare 全局邮件列表返回某个不在 `temp_emails` 中的地址邮件
- **THEN** 系统 SHALL 仍然展示该邮件，并且 SHALL NOT 创建本地临时邮箱记录。

#### Scenario: 全局邮件不缓存为临时邮箱邮件
- **WHEN** 系统列出 Cloudflare 全局邮件
- **THEN** 系统 SHALL NOT 将这些邮件写入 `temp_email_messages`。

