## ADDED Requirements

### Requirement: Cloudflare channel records
系统 SHALL 支持已登录用户管理多套 Cloudflare Temp Email 渠道配置。

#### Scenario: 创建 Cloudflare 渠道
- **WHEN** 已登录用户提交渠道名称、Worker 域名、可选邮箱域名列表和管理员密码
- **THEN** 系统 SHALL 创建一个启用状态的 Cloudflare 渠道，并 SHALL 将管理员密码加密保存。

#### Scenario: 渠道名称唯一
- **WHEN** 已登录用户创建或重命名 Cloudflare 渠道为已存在的渠道名称，包括仅大小写不同的名称
- **THEN** 系统 SHALL 拒绝请求，并返回渠道名称已存在的错误。

#### Scenario: 渠道配置缺失
- **WHEN** 已登录用户创建或更新 Cloudflare 渠道，但渠道名称、Worker 域名或创建时的管理员密码缺失
- **THEN** 系统 SHALL 拒绝请求，并说明缺失字段。

#### Scenario: 列出 Cloudflare 渠道
- **WHEN** 已登录用户请求 Cloudflare 渠道列表
- **THEN** 系统 SHALL 返回每个渠道的 ID、名称、Worker 域名、邮箱域名列表、启用状态、默认状态和是否已配置管理员密码。

#### Scenario: 更新 Cloudflare 渠道
- **WHEN** 已登录用户更新 Cloudflare 渠道的名称、Worker 域名、邮箱域名列表、管理员密码或启用状态
- **THEN** 系统 SHALL 保存更新后的渠道配置，并 SHALL 在未提交新管理员密码时保留原管理员密码。

### Requirement: Default Cloudflare channel migration
系统 SHALL 将旧的全局 Cloudflare 配置迁移为默认 Cloudflare 渠道。

#### Scenario: 旧配置迁移为默认渠道
- **WHEN** 数据库存在旧的 Cloudflare Worker 域名和管理员密码配置，且尚未存在 Cloudflare 渠道
- **THEN** 系统 SHALL 创建一个默认 Cloudflare 渠道，并使用旧配置填充该渠道。

#### Scenario: 已有 Cloudflare 邮箱绑定默认渠道
- **WHEN** 迁移运行且存在 `provider='cloudflare'` 但没有渠道归属的临时邮箱
- **THEN** 系统 SHALL 将这些临时邮箱绑定到默认 Cloudflare 渠道。

#### Scenario: 默认渠道唯一
- **WHEN** 系统创建或设置默认 Cloudflare 渠道
- **THEN** 系统 SHALL 确保最多只有一个启用的 Cloudflare 渠道被标记为默认渠道。

#### Scenario: 旧配置不存在
- **WHEN** 数据库没有可用的旧 Cloudflare Worker 域名或管理员密码配置
- **THEN** 系统 SHALL NOT 创建空的默认 Cloudflare 渠道。

### Requirement: Cloudflare temp email channel binding
系统 SHALL 将每个 Cloudflare 临时邮箱绑定到所属 Cloudflare 渠道，并在后续操作中使用该渠道。

#### Scenario: 按渠道创建 Cloudflare 临时邮箱
- **WHEN** 已登录用户选择 Cloudflare 渠道和域名创建临时邮箱
- **THEN** 系统 SHALL 使用所选渠道的 Worker 域名和管理员密码调用创建地址接口，并 SHALL 将创建出的邮箱绑定到该渠道。

#### Scenario: 创建时只使用所选渠道域名
- **WHEN** 已登录用户选择某个 Cloudflare 渠道创建临时邮箱
- **THEN** 系统 SHALL 只允许使用该渠道配置的邮箱域名创建地址。

#### Scenario: 禁用渠道不可用于新建
- **WHEN** 已登录用户尝试使用禁用的 Cloudflare 渠道创建临时邮箱
- **THEN** 系统 SHALL 拒绝请求，并说明该渠道不可用于新建邮箱。

#### Scenario: 按所属渠道读取 Cloudflare 临时邮箱邮件
- **WHEN** 已登录用户读取某个 Cloudflare 临时邮箱邮件
- **THEN** 系统 SHALL 使用该邮箱绑定渠道的 Worker 域名和该邮箱保存的 JWT 请求上游邮件列表。

#### Scenario: 按所属渠道删除 Cloudflare 上游地址
- **WHEN** 已登录用户删除某个 Cloudflare 临时邮箱
- **THEN** 系统 SHALL 使用该邮箱绑定渠道的 Worker 域名和管理员密码清理上游地址。

#### Scenario: Cloudflare 邮箱缺少渠道归属
- **WHEN** 系统需要读取或删除 Cloudflare 临时邮箱，但该邮箱没有渠道归属且不存在可用默认渠道
- **THEN** 系统 SHALL 返回失败响应，并说明缺少 Cloudflare 渠道归属。

### Requirement: Cloudflare channel deletion protection
系统 SHALL 防止删除仍被 Cloudflare 临时邮箱引用的渠道。

#### Scenario: 删除未引用渠道
- **WHEN** 已登录用户删除没有任何 Cloudflare 临时邮箱引用的渠道
- **THEN** 系统 SHALL 删除该渠道配置。

#### Scenario: 拒绝删除被引用渠道
- **WHEN** 已登录用户删除仍被一个或多个 Cloudflare 临时邮箱引用的渠道
- **THEN** 系统 SHALL 拒绝删除，并返回引用数量或可理解的占用说明。

#### Scenario: 禁用被引用渠道
- **WHEN** 已登录用户禁用仍被 Cloudflare 临时邮箱引用的渠道
- **THEN** 系统 SHALL 保留该渠道和邮箱归属，并 SHALL 阻止该渠道用于创建新邮箱和查看渠道全部邮件。

### Requirement: Cloudflare channel domains
系统 SHALL 按 Cloudflare 渠道返回可用邮箱域名。

#### Scenario: 查询指定渠道域名
- **WHEN** 已登录用户请求某个启用 Cloudflare 渠道的域名列表
- **THEN** 系统 SHALL 返回该渠道配置的邮箱域名列表；若该渠道未配置邮箱域名，系统 SHALL 返回成功响应和空列表。

#### Scenario: 查询禁用渠道域名
- **WHEN** 已登录用户请求禁用 Cloudflare 渠道的域名列表
- **THEN** 系统 SHALL 返回失败响应，并说明该渠道不可用。

#### Scenario: 查询不存在渠道域名
- **WHEN** 已登录用户请求不存在的 Cloudflare 渠道域名列表
- **THEN** 系统 SHALL 返回失败响应，并说明渠道不存在。

### Requirement: Cloudflare channel import and export
系统 SHALL 在 Cloudflare 临时邮箱导入和导出中保留渠道信息。

#### Scenario: 按渠道分段导出
- **WHEN** 已登录用户导出临时邮箱分组且存在 Cloudflare 临时邮箱
- **THEN** 系统 SHALL 按 Cloudflare 渠道输出 `[cloudflare:<channel_name>]` 分段，并在对应分段下输出该渠道的邮箱和 JWT。

#### Scenario: 按渠道分段导入
- **WHEN** 已登录用户导入包含 `[cloudflare:<channel_name>]` 分段的临时邮箱数据
- **THEN** 系统 SHALL 将该分段下的 Cloudflare 临时邮箱绑定到名称匹配的 Cloudflare 渠道。

#### Scenario: 旧 Cloudflare 格式导入
- **WHEN** 已登录用户导入旧 `[cloudflare]` 分段或旧 `email----jwt` Cloudflare 格式
- **THEN** 系统 SHALL 将导入的 Cloudflare 临时邮箱绑定到默认 Cloudflare 渠道。

#### Scenario: 导入不存在渠道
- **WHEN** 已登录用户导入 `[cloudflare:<channel_name>]`，但对应渠道不存在
- **THEN** 系统 SHALL 跳过该分段或行，并返回可理解的渠道不存在错误。

#### Scenario: Cloudflare 邮箱地址保持全局唯一
- **WHEN** 已登录用户导入的 Cloudflare 邮箱地址已存在于本地临时邮箱列表
- **THEN** 系统 SHALL 更新该邮箱的 JWT 和渠道归属，而 SHALL NOT 创建重复邮箱记录。
