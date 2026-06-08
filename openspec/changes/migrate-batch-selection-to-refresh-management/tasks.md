## 1. Regression Coverage

- [x] 1.1 Add frontend structure tests that assert Token 刷新管理 exposes the full batch action toolbar and selection controls.
- [x] 1.2 Add regression coverage that `query_refreshable_accounts` returns the account summary fields needed by copied actions: aliases, account type, provider, forwarding state, tags and group metadata.
- [x] 1.3 Add or update tests that protect the existing main mailbox batch action entry points from regressions during shared-helper extraction.

## 2. Shared Batch Action Foundation

- [x] 2.1 Extract reusable account-selection data helpers so batch actions can operate on selected account summaries instead of only `#accountList` DOM checkboxes.
- [x] 2.2 Adapt existing copy, export, forwarding, proxy, tag, move and delete batch functions to accept a main-list or Token-management selection context.
- [x] 2.3 Keep existing main mailbox list behavior unchanged after helper extraction, including temporary mailbox handling where applicable.

## 3. Token Management Selection UI

- [x] 3.1 Update `refreshModal` markup with a selection-mode entry point and a selected-state batch toolbar containing all normal account actions.
- [x] 3.2 Implement Token list selection state, row click selection, checkbox selection, `Shift` range selection, drag selection,全选当前列表 and清空选择.
- [x] 3.3 Update Token account row rendering so selected rows, disabled rows and running rows stay visually distinct.
- [x] 3.4 Add responsive CSS so the Token batch toolbar remains usable on desktop and mobile without overlapping the table or task logs.

## 4. Token Management Batch Actions

- [x] 4.1 Wire Token 管理“刷新 Token” to the existing selected-account SSE task flow and keep task logs, stop task and conflict handling intact.
- [x] 4.2 Wire Token 管理“复制邮箱+别名” to copy primary emails and aliases from selected account summaries with de-duplication.
- [x] 4.3 Wire Token 管理“导出” to the existing export verification flow using selected account IDs.
- [x] 4.4 Wire Token 管理“开启转发”和“取消转发” to the existing forwarding batch API with matching eligibility and feedback.
- [x] 4.5 Wire Token 管理“代理” to the existing batch proxy modal and API.
- [x] 4.6 Wire Token 管理“标签+” and “标签-” to the existing batch tag modal and account tag API.
- [x] 4.7 Wire Token 管理“移动” to the existing batch move group modal and API.
- [x] 4.8 Wire Token 管理“删除” to the existing batch delete API with confirmation and deleted-account view reset.

## 5. Synchronization, Docs and Validation

- [x] 5.1 Ensure each successful mutating batch action invalidates account caches, refreshes groups, refreshes the Token list and refreshes the visible main account list.
- [x] 5.2 Clear Token selection on search/status scope changes and after completed destructive or state-changing actions.
- [x] 5.3 Update README and CHANGELOG to document the full Token 刷新管理批量操作 migration.
- [x] 5.4 Run targeted frontend/static regression tests and relevant Python tests for refresh management and account batch APIs.
- [x] 5.5 Run `openspec status --change migrate-batch-selection-to-refresh-management` and confirm the change is ready to apply.
