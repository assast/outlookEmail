## ADDED Requirements

### Requirement: Explicit Cloudflare AI username generation
系统 SHALL 支持已登录用户在 Cloudflare 临时邮箱生成弹窗中显式触发 AI 用户名生成，并 SHALL 在创建前展示可编辑的用户名列表。

#### Scenario: 按数量生成 AI 用户名
- **WHEN** 已登录用户在 Cloudflare 临时邮箱生成弹窗中输入有效数量并点击“AI生成”
- **THEN** 系统 SHALL 使用已保存且启用的 Cloudflare AI 用户名配置请求生成相同数量的用户名，并 SHALL 将结果按一行一个写入用户名多行文本。

#### Scenario: AI 生成直接覆盖已有用户名
- **WHEN** 用户名多行文本中已有内容且已登录用户点击“AI生成”
- **THEN** 系统 SHALL 在 AI 生成成功后直接用新生成的用户名列表覆盖原文本内容。

#### Scenario: AI 配置不可用
- **WHEN** 已登录用户点击“AI生成”，但 Cloudflare AI 用户名功能未启用或 API 地址、模型、API Key 缺失
- **THEN** 系统 SHALL 拒绝生成请求，并 SHALL 返回可理解的配置缺失错误。

#### Scenario: AI 返回数量不足
- **WHEN** AI 生成接口返回的可用用户名数量少于请求数量
- **THEN** 系统 SHALL 返回失败响应，并 SHALL NOT 使用随机用户名补齐。

#### Scenario: AI 返回数量过多
- **WHEN** AI 生成接口返回的可用用户名数量多于请求数量
- **THEN** 系统 SHALL 返回失败响应，并 SHALL NOT 截断为请求数量。

#### Scenario: AI 清洗后数量不匹配
- **WHEN** AI 返回内容经过小写化、去域名、字符清洗、长度校验和去重后数量不等于请求数量
- **THEN** 系统 SHALL 返回失败响应，并 SHALL NOT 将部分结果写入用户名多行文本。

#### Scenario: AI 生成不创建邮箱
- **WHEN** 已登录用户点击“AI生成”并成功获得用户名列表
- **THEN** 系统 SHALL NOT 创建任何 Cloudflare 临时邮箱，直到用户提交创建操作。

### Requirement: Cloudflare username multiline input
系统 SHALL 在 Cloudflare 临时邮箱生成弹窗中使用多行文本接收显式用户名列表。

#### Scenario: 展示多行用户名输入
- **WHEN** 已登录用户在生成临时邮箱弹窗中选择 Cloudflare 提供商
- **THEN** 系统 SHALL 展示用户名多行文本，并 SHALL 说明一行一个用户名。

#### Scenario: 用户名为空时随机生成
- **WHEN** 已登录用户提交 Cloudflare 批量创建且用户名多行文本为空
- **THEN** 系统 SHALL 按提交数量随机生成对应数量的用户名。

#### Scenario: 用户名数量严格匹配
- **WHEN** 已登录用户提交 Cloudflare 批量创建且用户名多行文本存在一个或多个非空行
- **THEN** 系统 SHALL 要求有效用户名数量严格等于提交数量，否则 SHALL 拒绝请求。

#### Scenario: 用户名列表包含重复项
- **WHEN** 已登录用户提交的用户名多行文本在清洗后存在重复用户名
- **THEN** 系统 SHALL 拒绝请求，并 SHALL 说明用户名不能重复。

#### Scenario: 用户名列表包含非法项
- **WHEN** 已登录用户提交的用户名多行文本中存在清洗后为空、过短或不符合 Cloudflare 用户名规则的非空行
- **THEN** 系统 SHALL 拒绝请求，并 SHALL 说明用户名格式无效。

#### Scenario: 提交创建不隐式调用 AI
- **WHEN** 已登录用户提交 Cloudflare 批量创建
- **THEN** 系统 SHALL 只使用显式提交的用户名列表或随机用户名，并 SHALL NOT 在提交阶段调用 AI 用户名生成。
