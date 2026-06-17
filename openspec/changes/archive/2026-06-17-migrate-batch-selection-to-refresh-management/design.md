## Context

主邮箱列表已经有成熟的批量选择和批量操作体系，包含选择模式、行点击、`Shift` 范围选择、拖拽选择、浮动批量工具条，以及刷新 Token、复制邮箱+别名、导出、转发、代理、标签、移动和删除等账号动作。

Token 刷新管理目前是独立弹窗工作台，列表只提供表格复选框、当前列表全选、清空、刷新已选和删除已选。用户在 Token 刷新管理中通过状态或搜索筛出账号后，如果要执行其它账号批量动作，需要回到主邮箱列表重新筛选和选择。

## Goals / Non-Goals

**Goals:**

- 在 Token 刷新管理账号列表中提供与主邮箱列表一致的批量选择体验。
- 在 Token 刷新管理中提供普通邮箱列表已有的全部账号批量动作。
- 复用现有账号批量 API，避免新增后端数据模型。
- 保留 Token 刷新管理现有流式刷新任务、任务日志和停止任务能力。
- 批量动作完成后同步刷新 Token 管理列表、主账号列表、分组计数和本地缓存。

**Non-Goals:**

- 不把临时邮箱批量动作移入 Token 刷新管理。
- 不改变 Token 刷新管理的账号数据范围；仍以 active Outlook 账号为主。
- 不新增批量重新授权能力。
- 不改变现有账号批量 API 的认证、CSRF 或导出二次验证规则。

## Decisions

### Decision: Token 页复用账号批量 API，不新增专用后端接口

Token 刷新管理列表返回的账号摘要已经包含 `email`、`aliases`、`account_type`、`provider`、`forward_enabled`、`tags`、分组和刷新状态等信息，足以驱动前端资格判断与按钮文案。批量动作可以复用现有接口：

- 刷新 Token：`POST /api/accounts/refresh-selected-stream`
- 导出：`POST /api/accounts/export-selected`
- 转发：`POST /api/accounts/batch-update-forwarding`
- 代理：`POST /api/accounts/batch-update-proxy`
- 标签：`POST /api/accounts/tags`
- 移动：`POST /api/accounts/batch-update-group`
- 删除：`POST /api/accounts/batch-delete`

替代方案是新增一组 `/api/refresh-management/*` 接口。这个方案会让后端行为重复，并增加两个入口之间的规则漂移风险，因此不采用。

### Decision: 刷新已选继续使用 SSE 任务链路

主邮箱列表里的批量刷新目前使用同步 `POST /api/accounts/refresh-selected`。Token 刷新管理已经使用 `POST /api/accounts/refresh-selected-stream` 初始化任务，再订阅 SSE 日志。迁移动作时只迁移动作入口与选择体验，不回退到同步刷新。

替代方案是为了动作一致性复制主邮箱列表同步刷新逻辑。这个方案会丢失 Token 刷新管理的任务日志、停止任务、冲突提示和账号级实时结果，因此不采用。

### Decision: 抽取或适配共享批量动作逻辑，避免复制完整函数

主邮箱列表的批量动作函数当前强依赖 `#accountList` DOM 和 `.account-select-checkbox`。实现时应优先抽取可复用的数据驱动函数，例如“获取选中账号摘要”“复制邮箱+别名”“启动导出”“更新转发”“更新代理”“更新标签”“移动分组”“删除账号后刷新缓存”。主邮箱列表和 Token 列表分别提供选中账号来源。

替代方案是在 `08-refresh.js` 中复制所有批量动作函数。这个方案实现更快，但后续维护会出现两套确认文案、错误处理和缓存刷新逻辑，因此只在抽取成本明显过高时局部复制薄包装。

### Decision: Token 列表选择范围限定为当前渲染列表

Token 刷新管理有搜索、状态筛选和分页大小。批量选择中的“全选当前列表”只作用于当前已渲染的列表项；搜索或状态筛选变化时清空选择，避免对不可见账号执行误操作。摘要文案必须明确当前选中数量。

替代方案是保留跨筛选隐藏选中项。这个方案适合高级批量构造，但对删除、移动和代理等破坏性或半破坏性动作风险更高，因此不采用。

## Risks / Trade-offs

- [Risk] 批量动作按钮过多导致 Token 管理列表头部拥挤 -> 使用与主邮箱列表一致的选中后工具条，未选中时不展示完整动作组。
- [Risk] 主邮箱列表和 Token 列表共享逻辑抽取不当会影响已有批量操作 -> 先补充主邮箱列表回归测试，再做小范围抽取，保留原有 DOM 入口。
- [Risk] 删除、移动、标签等动作完成后两个列表状态不一致 -> 动作成功后统一调用缓存失效、分组刷新、Token 列表刷新和当前账号视图重置。
- [Risk] 导出动作需要二次验证，Token 弹窗内触发导出验证可能出现弹层顺序问题 -> 复用现有导出验证弹窗，并验证其能覆盖 Token 管理弹窗。
- [Risk] Token 列表只包含 active Outlook 账号，批量转发/代理/标签/移动会修改账号管理属性 -> 文案明确为账号批量动作，并沿用主邮箱列表确认提示。

## Migration Plan

1. 在 Token 刷新管理模板中加入选择模式入口和选中后批量工具条。
2. 为 Token 列表行绑定与主邮箱列表一致的行点击、复选框、`Shift` 和拖拽选择行为。
3. 抽取或适配账号批量动作函数，让 Token 列表能以账号摘要数组作为动作输入。
4. 保留 Token 页现有流式刷新实现，并接入新的“刷新 Token”批量按钮。
5. 为复制、导出、转发、代理、标签、移动、删除接入现有接口和弹窗。
6. 补充回归测试并更新 README、CHANGELOG 或 API 文档说明。

Rollback 可以移除 Token 管理模板中的新增工具条入口，并让 `08-refresh.js` 回到现有表格复选框和四个基础按钮；后端接口不需要回滚。

## Open Questions

无。
