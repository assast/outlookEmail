## ADDED Requirements

### Requirement: Deterministic email query candidates
系统 SHALL 基于请求邮箱地址生成确定性的邮箱查询候选列表。

#### Scenario: 完整地址候选
- **WHEN** 系统为有效请求邮箱地址构建候选列表
- **THEN** 第一个候选地址 SHALL 是完整归一化后的请求地址。

#### Scenario: Plus-address 候选
- **WHEN** 请求邮箱的本地部分包含 plus-address 片段
- **THEN** 系统 SHALL 在保留原始域名的前提下，从右到左逐级移除 plus-address 片段并追加候选地址。

#### Scenario: 非 Gmail 地址候选
- **WHEN** 请求邮箱域名既不是 `gmail.com` 也不是 `googlemail.com`
- **THEN** 系统 SHALL NOT 添加 Gmail/Googlemail 后缀回退候选地址。

### Requirement: Gmail and Googlemail suffix fallback
系统 SHALL 在邮箱查找和 Cloudflare 地址过滤查询中支持 `@gmail.com` 与 `@googlemail.com` 互相回退。

#### Scenario: Gmail 回退到 Googlemail
- **WHEN** 请求地址以 `@gmail.com` 结尾，且该请求地址未找到结果
- **THEN** 系统 SHALL 使用相同本地部分和 `@googlemail.com` 后缀重试。

#### Scenario: Googlemail 回退到 Gmail
- **WHEN** 请求地址以 `@googlemail.com` 结尾，且该请求地址未找到结果
- **THEN** 系统 SHALL 使用相同本地部分和 `@gmail.com` 后缀重试。

#### Scenario: Plus 回退与 Gmail 后缀回退组合
- **WHEN** 请求的 Gmail 或 Googlemail 地址包含 plus-address 片段
- **THEN** 系统 SHALL 先评估原始后缀下的 plus-address 候选，再评估另一后缀下的等价候选。

### Requirement: Account API fallback resolution
系统 SHALL 在内部和对外邮件 API 的账号解析中使用共享邮箱查询候选顺序。

#### Scenario: 内部邮件 API 解析 Gmail 另一后缀
- **WHEN** `/api/emails/<email_addr>` 请求的是 Gmail 或 Googlemail 地址，且没有直接账号匹配
- **THEN** 系统 SHALL 在返回账号不存在前，使用另一后缀重试账号解析。

#### Scenario: 对外邮件 API 解析 Gmail 另一后缀
- **WHEN** `/api/external/emails` 请求的是 Gmail 或 Googlemail 地址，且没有直接账号匹配
- **THEN** 系统 SHALL 在返回账号不存在前，使用另一后缀重试账号解析。

#### Scenario: 返回解析元数据
- **WHEN** 内部或对外邮件 API 的账号解析使用了回退候选
- **THEN** 成功响应 SHALL 包含原始请求邮箱和解析得到的账号邮箱，并在适用时标明别名或回退元数据。

### Requirement: Cloudflare address-filter fallback
系统 SHALL 只在 Cloudflare 全局邮件查询提供具体地址过滤条件时，应用 Gmail/Googlemail 回退。

#### Scenario: Cloudflare 地址过滤重试另一后缀
- **WHEN** Cloudflare 全局邮件查询包含 Gmail 或 Googlemail 地址过滤条件，且第一次查询成功但返回 0 封邮件
- **THEN** 系统 SHALL 在返回空结果前查询另一后缀候选地址。

#### Scenario: Cloudflare 地址过滤已有结果时不回退
- **WHEN** Cloudflare 全局邮件查询包含 Gmail 或 Googlemail 地址过滤条件，且第一次查询返回一封或多封邮件
- **THEN** 系统 SHALL NOT 查询另一后缀候选地址。

#### Scenario: Cloudflare 无过滤查询不回退
- **WHEN** Cloudflare 全局邮件查询不包含地址过滤条件
- **THEN** 系统 SHALL NOT 生成或应用 Gmail/Googlemail 回退候选地址。

#### Scenario: 返回 Cloudflare 回退元数据
- **WHEN** Cloudflare 地址过滤查询从回退候选地址返回邮件
- **THEN** 响应 SHALL 包含请求地址、实际查询地址，并将 `fallback_used` 设置为 true。
