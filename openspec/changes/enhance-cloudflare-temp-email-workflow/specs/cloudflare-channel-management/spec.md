## ADDED Requirements

### Requirement: Cloudflare temp email batch generation
系统 SHALL 支持已登录用户按数量批量创建 Cloudflare 临时邮箱，并 SHALL 将创建成功的邮箱绑定到所选 Cloudflare 渠道。

#### Scenario: 按数量批量创建 Cloudflare 临时邮箱
- **WHEN** 已登录用户提交有效启用的 Cloudflare 渠道、有效域名和 `1-50` 范围内的创建数量
- **THEN** 系统 SHALL 使用该渠道的 Worker 域名和管理员密码逐个调用创建地址接口，并 SHALL 将每个创建成功的邮箱保存为 `provider='cloudflare'` 且绑定到该渠道。

#### Scenario: 批量创建数量无效
- **WHEN** 已登录用户提交小于 1、大于 50 或无法解析为整数的 Cloudflare 批量创建数量
- **THEN** 系统 SHALL 拒绝请求，并说明数量必须在允许范围内。

#### Scenario: 批量创建禁用渠道
- **WHEN** 已登录用户尝试使用禁用的 Cloudflare 渠道批量创建临时邮箱
- **THEN** 系统 SHALL 拒绝请求，并说明该渠道不可用于新建邮箱。

#### Scenario: 批量创建部分失败
- **WHEN** Cloudflare 批量创建过程中部分上游创建请求失败或返回数据不完整
- **THEN** 系统 SHALL 保留已创建成功的邮箱，并 SHALL 在响应中返回成功邮箱列表、失败数量和可理解的失败明细。

#### Scenario: 批量创建全部失败
- **WHEN** Cloudflare 批量创建过程中没有任何邮箱创建成功
- **THEN** 系统 SHALL 返回失败响应，并保留有用的失败原因。

#### Scenario: 批量创建绑定标签
- **WHEN** 已登录用户批量创建 Cloudflare 临时邮箱时提交一个或多个标签 ID
- **THEN** 系统 SHALL 将每个创建成功的临时邮箱绑定到存在的标签，并 SHALL 忽略不存在的标签 ID。

## MODIFIED Requirements

### Requirement: Cloudflare channel import and export
系统 SHALL 在 Cloudflare 临时邮箱导入和导出中保留渠道信息，并 SHALL 在导入界面展示渠道文本写法且支持导入时绑定标签。

#### Scenario: 按渠道分段导出
- **WHEN** 已登录用户导出临时邮箱分组且存在 Cloudflare 临时邮箱
- **THEN** 系统 SHALL 按 Cloudflare 渠道输出 `[cloudflare:<channel_name>]` 分段，并在对应分段下输出该渠道的邮箱和 JWT。

#### Scenario: 按渠道分段导入
- **WHEN** 已登录用户导入包含 `[cloudflare:<channel_name>]` 分段的临时邮箱数据
- **THEN** 系统 SHALL 将该分段下的 Cloudflare 临时邮箱绑定到名称匹配的 Cloudflare 渠道。

#### Scenario: 导入格式提示展示渠道写法
- **WHEN** 已登录用户在临时邮箱导入界面选择 Cloudflare 提供商
- **THEN** 系统 SHALL 在格式提示或示例中展示 `[cloudflare:<channel_name>]` 分段写法和 `email----jwt----channel_name` 行写法。

#### Scenario: 按行渠道名导入
- **WHEN** 已登录用户导入包含 `email----jwt----channel_name` 行格式的 Cloudflare 临时邮箱数据
- **THEN** 系统 SHALL 将该行 Cloudflare 临时邮箱绑定到名称匹配的 Cloudflare 渠道。

#### Scenario: 旧 Cloudflare 格式导入
- **WHEN** 已登录用户导入旧 `[cloudflare]` 分段或旧 `email----jwt` Cloudflare 格式
- **THEN** 系统 SHALL 将导入的 Cloudflare 临时邮箱绑定到默认 Cloudflare 渠道。

#### Scenario: 导入绑定标签
- **WHEN** 已登录用户导入 Cloudflare 临时邮箱时提交一个或多个标签 ID，且某些邮箱被新增或更新成功
- **THEN** 系统 SHALL 将新增或更新成功的 Cloudflare 临时邮箱绑定到存在的标签，并 SHALL 忽略不存在的标签 ID。

#### Scenario: 导入不存在渠道
- **WHEN** 已登录用户导入 `[cloudflare:<channel_name>]`，但对应渠道不存在
- **THEN** 系统 SHALL 跳过该分段或行，并返回可理解的渠道不存在错误。

#### Scenario: Cloudflare 邮箱地址保持全局唯一
- **WHEN** 已登录用户导入的 Cloudflare 邮箱地址已存在于本地临时邮箱列表
- **THEN** 系统 SHALL 更新该邮箱的 JWT 和渠道归属，而 SHALL NOT 创建重复邮箱记录。
