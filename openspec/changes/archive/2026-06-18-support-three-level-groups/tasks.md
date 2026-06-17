## 1. 数据库 Schema 与迁移

- [x] 1.1 `01_bootstrap.py`: groups 表 CREATE 语句新增 `parent_id INTEGER DEFAULT NULL` 和 `level INTEGER DEFAULT 1 CHECK(level IN (1,2,3))`，加 `FOREIGN KEY(parent_id) REFERENCES groups(id)`
- [x] 1.2 `01_bootstrap.py`: 新增迁移脚本 `ALTER TABLE groups ADD COLUMN parent_id INTEGER DEFAULT NULL` 和 `ALTER TABLE groups ADD COLUMN level INTEGER DEFAULT 1`，对已有行 `UPDATE groups SET parent_id = NULL, level = 1 WHERE parent_id IS NULL`
- [x] 1.3 `01_bootstrap.py`: 为 `parent_id` 列添加索引 `CREATE INDEX IF NOT EXISTS idx_groups_parent_id ON groups(parent_id)`

## 2. 后端数据层 — 分组层级操作

- [x] 2.1 `02_groups_accounts.py`: 新增 `get_descendant_group_ids(group_id)` 函数，返回包含自身在内的所有后代分组 ID 列表
- [x] 2.2 `02_groups_accounts.py`: 新增 `get_child_groups(parent_id)` 函数，返回指定父分组的直接子分组列表
- [x] 2.3 `02_groups_accounts.py`: 新增 `rebuild_group_levels(group_id)` 函数，级联修正子树的 level 值
- [x] 2.4 `02_groups_accounts.py`: 新增 `get_max_subtree_depth(group_id)` 函数，计算分组及其子树的最大深度
- [x] 2.5 `02_groups_accounts.py`: 新增 `validate_group_move(group_id, target_parent_id)` 函数，校验移动后层级深度不超过 3
- [x] 2.6 `02_groups_accounts.py`: 改造 `load_groups()` — 按 parent_id, level, sort_order 排序返回，并附带 `descendant_account_count`
- [x] 2.7 `02_groups_accounts.py`: 改造 `add_group()` — 增加 `parent_id` 参数，自动计算 level，校验父分组合法性和层级深度
- [x] 2.8 `02_groups_accounts.py`: 改造 `update_group()` — 支持 `parent_id` 变更，移动时级联修正子树 level
- [x] 2.9 `02_groups_accounts.py`: 改造 `delete_group()` — 递归收集所有后代分组 ID，将所有关联账号移回默认分组 (id=1)，然后删除所有后代分组及自身
- [x] 2.10 `02_groups_accounts.py`: 改造 `reorder_groups()` — 增加 `parent_id` 参数，只重排指定父级下的子分组 sort_order
- [x] 2.11 `02_groups_accounts.py`: 改造 `get_group_account_count()` — 新增 `recursive` 参数，为 True 时返回后代账号总数
- [x] 2.12 `02_groups_accounts.py`: 改造 `get_movable_group_ids()` — 增加 `parent_id` 过滤参数

## 3. 后端数据层 — 代理级联回退

- [x] 3.1 `02_groups_accounts.py`: 新增 `get_group_inherited_proxy_config(group_row)` 函数，沿 parent_id 向上查找第一个有代理配置的祖先分组
- [x] 3.2 `02_groups_accounts.py`: 改造 `get_account_proxy_config()` — 分组代理部分改为调用 `get_group_inherited_proxy_config()` 逐级回退

## 4. 后端数据层 — 递归账号查询

- [x] 4.1 `02_groups_accounts.py`: 改造 `load_accounts(group_id=X)` 为递归查询，匹配分组自身及所有后代分组
- [x] 4.2 `02_groups_accounts.py`: 改造 `count_accounts(group_id=X)` 为递归账号统计
- [x] 4.3 `02_groups_accounts.py`: 改造 `search_account_records()` 的 group_id 参数为递归分组过滤

## 5. 后端 API 路由

- [x] 5.1 `04_routes_groups_accounts.py`: `GET /api/groups` 返回增加 `parent_id`, `level`, `descendant_account_count` 字段
- [x] 5.2 `04_routes_groups_accounts.py`: `POST /api/groups` 增加 `parent_id` 参数，校验层级深度 ≤ 3，拒绝临时邮箱分组作为父分组
- [x] 5.3 `04_routes_groups_accounts.py`: `PUT /api/groups/<id>` 支持 `parent_id` 变更，校验移动合法性
- [x] 5.4 `04_routes_groups_accounts.py`: `DELETE /api/groups/<id>` 改用级联删除逻辑，返回信息中包含被删除的子分组数量
- [x] 5.5 `04_routes_groups_accounts.py`: `PUT /api/groups/reorder` 增加 `parent_id` 参数，只在同父级下排序
- [x] 5.6 `04_routes_groups_accounts.py`: `POST /api/accounts/batch-update-group` 验证目标分组存在性（支持任意层级分组）

## 6. 前端 JS — 树形渲染与交互

- [x] 6.1 `02-groups.js`: 新增 `buildGroupTree(flatGroups)` 函数，将扁平数组构建为 parent_id → children 嵌套结构
- [x] 6.2 `02-groups.js`: 改造 `renderGroupList()` → `renderGroupTree(nodes, level)` 递归渲染树形分组列表
- [x] 6.3 `02-groups.js`: 新增折叠/展开 toggle 交互逻辑，点击箭头切换子分组显隐，状态存 localStorage
- [x] 6.4 `02-groups.js`: 新增 `expandAncestors(groupId)` 函数，选中被折叠的子分组时自动展开其祖先
- [x] 6.5 `02-groups.js`: 改造 `selectGroup()` — 调用 API 时传递 group_id，账号面板展示当前分组及后代分组账号
- [x] 6.6 `02-groups.js`: 改造 `loadGroups()` — 处理 API 返回的 parent_id 和 level 字段，构建树形结构后渲染

## 7. 前端 JS — 拖拽重构

- [x] 7.1 `02-groups.js`: 改造拖拽逻辑支持两种目标模式 — "移入分组"（目标分组的上部区域）和"同级排序"（分组间间隔线）
- [x] 7.2 `02-groups.js`: 新增拖拽移入时的视觉反馈 — 目标分组高亮边框
- [x] 7.3 `02-groups.js`: 新增拖拽移入操作的 API 调用 — `PUT /api/groups/<id>` 更新 parent_id
- [x] 7.4 `02-groups.js`: 新增层级深度校验 — 移入操作前校验目标深度 + 子树深度 ≤ 3，非法时显示拒绝高亮并提示
- [x] 7.5 `02-groups.js`: 改造 `persistGroupOrder()` — 传递 parent_id 参数

## 8. 前端 JS — 模态框与关联功能

- [x] 8.1 `dialogs-primary.html`: 添加/编辑分组模态框新增"父分组"下拉选择器，可选"无（一级分组）"或现有分组
- [x] 8.2 `02-groups.js`: 新增父分组下拉动态逻辑 — 排除三级分组和临时邮箱分组，编辑时当前分组及其后代也不可选
- [x] 8.3 `02-groups.js`: 改造 `saveGroup()` — 提交时包含 `parent_id` 参数
- [x] 8.4 `02-groups.js`: 改造 `editGroup()` — 加载并回填 parent_id 到下拉
- [x] 8.5 `02-groups.js`: 改造 `showAddGroupModal()` — 重置父分组下拉，传入当前选中分组作为默认父分组
- [x] 8.6 `02-groups.js`: 改造 `deleteGroup()` — 确认弹窗显示子分组数量
- [x] 8.7 `02-groups.js`: 改造 `updateGroupSelects()` — 分组下拉以树形缩进展示（一级无缩进、二级 2 空格、三级 4 空格）

## 9. CSS 样式

- [x] 9.1 `03-layout.css`: 新增 `.group-item.level-1/.level-2/.level-3` 缩进样式 (padding-left: 16/36/56px)
- [x] 9.2 `03-layout.css`: 新增 `.group-toggle` 箭头样式 — 16px 宽、居中、transition 旋转动画
- [x] 9.3 `03-layout.css`: 新增 `.group-toggle.collapsed` 旋转 -90 度
- [x] 9.4 `03-layout.css`: 新增拖拽移入目标高亮样式 `.group-item.drop-target`（蓝色边框 + 微蓝背景）
- [x] 9.5 `03-layout.css`: 新增拖拽拒绝高亮样式 `.group-item.drop-rejected`（红色边框）

## 10. 集成验证

- [x] 10.1 验证已有扁平数据迁移后功能正常（所有分组 parent_id=NULL, level=1，行为与升级前一致）
- [x] 10.2 验证三级分组的创建、编辑、删除（含级联）完整流程
- [x] 10.3 验证代理级联回退正确性（三级→二级→一级→空）
- [x] 10.4 验证选中非叶子节点时展示自身及后代分组账号
- [x] 10.5 验证跨层级拖拽和层级深度校验
- [x] 10.6 验证折叠/展开状态持久化和自动展开祖先
- [x] 10.7 验证分组下拉选择器的树形缩进展示
