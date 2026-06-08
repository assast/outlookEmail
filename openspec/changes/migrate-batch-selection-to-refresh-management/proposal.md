## Why

Token 刷新管理里的账号列表已经承担筛选、查看刷新状态和批量刷新/删除职责，但批量交互能力明显弱于主邮箱列表。用户在 Token 刷新管理里筛选出目标账号后，仍需要回到主邮箱列表才能执行复制、导出、标签、移动、代理、转发等批量动作，流程割裂且容易丢失当前筛选上下文。

## What Changes

- Token 刷新管理账号列表完整移植邮箱列表的批量选择体验：选择模式、行点击选择、复选框选择、`Shift` 连续范围选择、拖拽选择、全选当前列表和清空选择。
- Token 刷新管理账号列表完整移植普通邮箱列表的批量动作：刷新 Token、复制邮箱+别名、导出、开启转发、取消转发、账号代理、标签+、标签-、移动分组和删除。
- Token 刷新管理继续使用现有流式刷新链路执行“刷新已选”，保留任务日志、停止任务、冲突提示和刷新结果回填。
- 批量动作完成后同步刷新 Token 刷新管理列表、主邮箱账号列表、分组计数和相关前端缓存，避免两个列表状态不一致。
- Token 刷新管理里的批量动作遵守与主邮箱列表一致的资格判断、二次确认、错误提示和执行结果反馈。
- 不引入破坏性变更。

## Capabilities

### New Capabilities

- `refresh-management-batch-actions`: Token 刷新管理账号列表中的批量选择、批量工具条和账号批量操作能力。

### Modified Capabilities

无。

## Impact

- 前端模板：`templates/partials/index/dialogs-management.html`
- 前端脚本：`static/js/index/08-refresh.js`、必要时复用或抽取 `static/js/index/10-batch-actions.js` 的通用选择/动作逻辑
- 前端样式：`static/css/index/06-modals-toast.css`，必要时复用邮箱列表批量工具条样式
- 后端接口：优先复用现有账号批量接口，包括 `/api/accounts/refresh-selected-stream`、`/api/accounts/export-selected`、`/api/accounts/batch-update-forwarding`、`/api/accounts/batch-update-proxy`、`/api/accounts/tags`、`/api/accounts/batch-update-group`、`/api/accounts/batch-delete`
- 测试与文档：补充前端结构回归、批量动作入口回归、README/API 或变更日志说明
