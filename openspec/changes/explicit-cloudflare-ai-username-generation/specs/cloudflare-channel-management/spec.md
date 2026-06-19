## ADDED Requirements

### Requirement: Cloudflare batch generation with explicit usernames
系统 SHALL 支持已登录用户在批量创建 Cloudflare 临时邮箱时提交显式用户名列表，并 SHALL 对该列表执行严格校验。

#### Scenario: 使用显式用户名列表批量创建
- **WHEN** 已登录用户提交有效启用的 Cloudflare 渠道、有效域名、`1-50` 范围内的创建数量和数量严格匹配的用户名列表
- **THEN** 系统 SHALL 按用户名列表顺序逐个调用 Cloudflare 创建地址接口，并 SHALL 将创建成功的邮箱保存为 `provider='cloudflare'` 且绑定到所选渠道。

#### Scenario: 用户名列表为空时随机批量创建
- **WHEN** 已登录用户提交有效启用的 Cloudflare 渠道、有效域名和 `1-50` 范围内的创建数量，但未提交用户名列表或提交空列表
- **THEN** 系统 SHALL 按提交数量随机生成用户名并逐个创建 Cloudflare 临时邮箱。

#### Scenario: 用户名列表数量少于创建数量
- **WHEN** 已登录用户提交的有效用户名数量少于 Cloudflare 批量创建数量
- **THEN** 系统 SHALL 拒绝请求，并 SHALL NOT 自动随机补齐缺少的用户名。

#### Scenario: 用户名列表数量多于创建数量
- **WHEN** 已登录用户提交的有效用户名数量多于 Cloudflare 批量创建数量
- **THEN** 系统 SHALL 拒绝请求，并 SHALL NOT 截断多余用户名。

#### Scenario: 用户名列表无效时不创建邮箱
- **WHEN** 已登录用户提交的用户名列表存在非法用户名、清洗后重复用户名或数量不匹配
- **THEN** 系统 SHALL 在调用 Cloudflare 创建地址接口前拒绝请求，并 SHALL NOT 创建任何邮箱。

#### Scenario: 批量创建提交阶段不使用 AI
- **WHEN** 已登录用户调用 Cloudflare 批量创建接口
- **THEN** 系统 SHALL NOT 在该请求中调用 AI 用户名生成逻辑；AI 用户名只 SHALL 通过显式 AI 生成接口产生。

#### Scenario: 显式用户名列表部分创建失败
- **WHEN** 用户名列表有效但 Cloudflare 上游对部分用户名创建失败或返回数据不完整
- **THEN** 系统 SHALL 保留已创建成功的邮箱，并 SHALL 在响应中返回成功邮箱列表、失败数量和包含对应用户名的失败明细。
