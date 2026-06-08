## ADDED Requirements

### Requirement: Token refresh management supports account batch selection

Token 刷新管理账号列表 SHALL 支持与主邮箱列表一致的批量选择体验，包括选择模式、行点击选择、复选框选择、`Shift` 连续范围选择、拖拽选择、全选当前列表和清空选择。

#### Scenario: Enter selection mode and select rows

- **WHEN** 用户在 Token 刷新管理账号列表中进入批量选择模式并点击账号行
- **THEN** 系统 SHALL 切换该账号的选中状态并更新已选数量

#### Scenario: Select a continuous range

- **WHEN** 用户先选中一个账号，再按住 `Shift` 点击同一 Token 列表中的另一个账号或复选框
- **THEN** 系统 SHALL 选中两个账号之间的连续范围并更新批量工具条状态

#### Scenario: Drag selection in selection mode

- **WHEN** 用户在批量选择模式下从账号行或复选框开始拖拽经过多个账号
- **THEN** 系统 SHALL 按拖拽起点状态批量选中或取消经过的账号

#### Scenario: Select and clear current list

- **WHEN** 用户点击 Token 刷新管理批量工具条中的全选当前列表或清空选择
- **THEN** 系统 SHALL 只更新当前已渲染 Token 列表中的账号选择状态

### Requirement: Token refresh management exposes all normal account batch actions

Token 刷新管理账号列表 SHALL 在选中账号后提供主邮箱列表普通账号支持的全部批量动作：刷新 Token、复制邮箱+别名、导出、开启转发、取消转发、账号代理、标签+、标签-、移动分组和删除。

#### Scenario: Show full batch action toolbar

- **WHEN** 用户在 Token 刷新管理账号列表中至少选中一个账号
- **THEN** 系统 SHALL 展示批量工具条，并包含刷新 Token、复制邮箱+别名、导出、开启转发、取消转发、代理、标签+、标签-、移动和删除操作

#### Scenario: Hide batch action toolbar when nothing is selected

- **WHEN** Token 刷新管理账号列表没有任何账号被选中
- **THEN** 系统 SHALL 隐藏选中态批量工具条或禁用全部选中态批量动作

#### Scenario: Preserve account action eligibility

- **WHEN** 已选账号不满足某个批量动作的资格条件
- **THEN** 系统 SHALL 按主邮箱列表同等规则禁用该动作或在执行时跳过不符合条件的账号，并显示明确提示

### Requirement: Selected Token refresh uses streaming task logs

Token 刷新管理中的刷新已选动作 MUST 使用现有选中账号流式刷新任务链路，并 SHALL 保留任务日志、停止任务、冲突提示和账号级刷新结果回填。

#### Scenario: Start selected refresh task

- **WHEN** 用户在 Token 刷新管理中选择账号并点击刷新 Token
- **THEN** 系统 SHALL 通过 `POST /api/accounts/refresh-selected-stream` 初始化任务，并使用返回的 `stream_url` 订阅 SSE 进度

#### Scenario: Render selected refresh progress

- **WHEN** 选中账号刷新任务返回开始、进度、账号结果、等待、完成、停止、冲突或错误事件
- **THEN** 系统 SHALL 更新任务日志、刷新统计、当前账号刷新状态和批量按钮可用状态

#### Scenario: Complete selected refresh task

- **WHEN** 选中账号流式刷新任务完成
- **THEN** 系统 SHALL 清空本次刷新选择、刷新 Token 管理列表，并同步刷新主邮箱列表缓存

### Requirement: Account batch actions execute from Token refresh management

Token 刷新管理 SHALL 允许用户对选中账号执行主邮箱列表已有的账号批量动作，并 MUST 复用现有账号批量接口和弹窗流程。

#### Scenario: Copy selected account emails and aliases

- **WHEN** 用户在 Token 刷新管理中选择账号并点击复制邮箱+别名
- **THEN** 系统 SHALL 复制选中账号的主邮箱和别名邮箱，去重后写入剪贴板

#### Scenario: Export selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并点击导出
- **THEN** 系统 SHALL 复用导出二次验证流程，并通过选中账号 ID 导出对应账号文本

#### Scenario: Update forwarding for selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并点击开启转发或取消转发
- **THEN** 系统 SHALL 调用账号批量转发接口，仅更新需要变更的账号并提示跳过数量或结果

#### Scenario: Update proxy for selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并点击代理
- **THEN** 系统 SHALL 复用账号代理设置弹窗，并将代理配置应用到选中账号

#### Scenario: Update tags for selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并点击标签+或标签-
- **THEN** 系统 SHALL 复用标签选择弹窗，并对选中账号批量添加或移除目标标签

#### Scenario: Move selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并点击移动
- **THEN** 系统 SHALL 复用移动分组弹窗，并把选中账号移动到目标普通分组

#### Scenario: Delete selected accounts

- **WHEN** 用户在 Token 刷新管理中选择账号并确认删除
- **THEN** 系统 SHALL 调用账号批量删除接口删除选中账号，并从 Token 刷新管理列表中移除已删除账号

### Requirement: Batch action results stay synchronized across account views

Token 刷新管理中的批量动作完成后，系统 SHALL 同步 Token 刷新管理列表、主邮箱账号列表、分组计数、当前账号视图和相关前端缓存。

#### Scenario: Refresh related views after successful batch mutation

- **WHEN** 用户在 Token 刷新管理中完成删除、移动、标签、代理、转发或导出以外的账号状态变更动作
- **THEN** 系统 SHALL 失效账号缓存、刷新分组列表、刷新 Token 管理列表，并刷新当前可见主邮箱账号列表

#### Scenario: Reset selected account after deletion

- **WHEN** Token 刷新管理批量删除的账号包含当前正在查看的邮箱
- **THEN** 系统 SHALL 清空当前账号和邮件详情视图，避免继续展示已删除账号的数据

#### Scenario: Preserve modal safety and feedback

- **WHEN** 用户从 Token 刷新管理执行删除、移动、代理、转发、标签、导出或刷新 Token 批量动作
- **THEN** 系统 MUST 显示与动作风险匹配的确认、加载、成功和失败反馈，并避免确认弹窗被 Token 管理弹窗遮挡
