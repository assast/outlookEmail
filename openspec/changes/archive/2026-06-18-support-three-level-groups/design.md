## Context

当前系统分组模型为扁平列表结构，`groups` 表仅有 `id, name, description, color, sort_order, is_system, proxy_url, fallback_proxy_url_1, fallback_proxy_url_2, created_at` 字段，无任何层级关系。所有分组同级排列，通过 `sort_order` 排序。`accounts.group_id` 外键指向单个分组。

前端分组面板 `#groupList` 渲染为简单列表，支持拖拽排序。分组操作（CRUD、排序、代理继承）均假设扁平结构。

约束：
- 技术栈：Flask + SQLite3 + 原生 JS（无框架）
- SQLite ≥ 3.8.3 支持 `WITH RECURSIVE` CTE
- 最大 3 级层级深度
- 已有生产数据需平滑迁移

## Goals / Non-Goals

**Goals:**
- 支持最多 3 级的树形分组结构
- 选中分组时展示该分组及所有后代分组账号
- 代理配置支持逐级向上回退继承
- 前端树形渲染，带折叠/展开交互
- 支持跨层级拖拽移动分组
- 删除分组时级联删除子分组，账号回退默认分组
- 所有关联功能（下拉选择器、批量操作等）适配树形展示

**Non-Goals:**
- 不支持超过 3 级的更深嵌套
- 不支持"虚拟分组"或"智能分组"等动态分类
- 不改变标签(tags)系统的扁平结构
- 不改变 IMAP 文件夹(folder)的概念

## Decisions

### D1: 层级数据模型 — Adjacency List (parent_id)

**选择**: 在 `groups` 表新增 `parent_id INTEGER DEFAULT NULL` 和 `level INTEGER DEFAULT 1 CHECK(level IN (1,2,3))`

**替代方案**:
- Path Enumeration (`level_path TEXT` 如 `"3/7/12"`)：查询子树高效（`LIKE '3/7/%'`），但移动子树需批量改写 path，且 SQLite 字符串操作不够直观。
- Nested Set (`lft/rgt`)：查询快但插入/移动代价高，对低频写高频读场景过度设计。
- Closure Table：额外一张表存所有祖先-后代对，3 级深度不值得。

**理由**: 层级最浅（仅 3 级），递归 CTE 性能足够，代码最简单直观。SQLite `WITH RECURSIVE` 可一次查询取全树，且移动/删除操作只需改 `parent_id`。

**约束**:
- `level=1` → `parent_id IS NULL`
- `level=2` → `parent_id` 指向 `level=1` 的分组
- `level=3` → `parent_id` 指向 `level=2` 的分组
- `name` 保持全局 UNIQUE（非同 parent 下唯一）

### D2: 代理继承 — 逐级向上回退

**选择**: `get_account_proxy_config()` 逻辑改为：账号自身覆盖 → 挂载分组 → 挂载分组父级 → 挂载分组祖父级 → 全局空值。

**理由**: 最直觉的继承方式——子分组不设代理就"继承"父分组。用户编辑子分组时可看到"当前继承自: XX分组"的提示。

**实现**: 新增 `get_group_inherited_proxy_config(group_row)` 函数，向上遍历 `parent_id` 直到找到有代理配置的分组或到达根节点。

### D3: 递归账号展示 — group_id 展开为分组子树

**选择**: `load_accounts(group_id=X)`、`count_accounts(group_id=X)` 和 `search_account_records(group_id=X)` 将 `X` 展开为自身及所有后代分组 ID，查询整个分组子树。

**理由**: 父分组代表其子树范围，用户在邮箱列表或导出中选择父分组时，预期包含子分组账号。后端导出对重叠的父子分组选择做账号去重，避免重复输出。

**API 影响**: `GET /api/accounts?group_id=X`、`GET /api/accounts/search?group_id=X` 和分组导出语义为“X 的子树账号”。

### D4: 折叠状态 — 前端 localStorage

**选择**: 折叠状态仅存前端 `localStorage`，key 格式 `outlook_group_collapsed_<groupId>`，不去数据库。

**理由**: 折叠是纯 UI 状态，多用户/多设备不应共享。

### D5: 跨层级拖拽 — 移入 + 排序双模式

**选择**:
1. 拖到另一个分组上方区域 → "移入该分组"（设 `parent_id` 为目标分组，`level` 相应调整）
2. 拖到分组之间的间隔线 → "在该层级此位置插入"（同 `parent_id` 下 `sort_order` 排序）

**约束**: 移入时校验目标深度 + 拖动子树深度 ≤ 3。

**拒绝的方案**: 仅支持同级排序 + 弹窗移动父级——交互碎片化，不如拖拽直观。

### D6: 删除策略 — 级联删除 + 账号回退

**选择**: 删除分组时，递归删除所有子分组。所有被删除分组（含子分组）下的账号 `group_id` 移回默认分组 (id=1)。

**拒绝的方案**:
- 子分组上移一级：可能导致同 parent 下名称冲突（需重命名），且语义可能不符用户预期。
- 拒绝删除有子分组的分组：用户需手动逐层清理，体验差。

### D7: 临时邮箱分组 — 限制为叶子不可的根节点

**选择**: 临时邮箱分组 (`is_system=1`) 保持一级根分组，不允许在其下创建子分组，也不允许将其移动为其他分组的子分组。

**理由**: 临时邮箱是特殊系统分组，其行为（渠道筛选、动态生成）与层级组织无关。

### D8: 排序范围 — 同 parent 下排序

**选择**: `sort_order` 仅在同 `parent_id` 下有意义。`reorder_groups()` 改为 `reorder_groups(parent_id, group_ids)`，只重排指定父级下的子分组。

**理由**: 不同父级的分组排序互不干扰，逻辑更清晰。

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 数据迁移：已有扁平分组需补 `parent_id=NULL, level=1` | `ALTER TABLE` + `UPDATE` 兜底，已有数据自然满足 |
| 名称全局唯一可能造成用户困扰：不同父级下不能同名 | 保持现有约束不变，避免复杂化；后续可按需放宽为同 parent 下唯一 |
| 跨层级拖拽校验复杂 | 仅 3 级深度，校验逻辑简单：`target_level + max_child_depth ≤ 3` |
| 后代范围和直属范围容易混淆 | 账号列表/搜索/导出/侧边栏数量统一使用分组子树；API 保留直属数和后代数两个字段 |
| 前端树形渲染重写工作量大 | 分组数量通常有限（几十到几百），DOM 操作无性能瓶颈 |
| 删除级联可能误删大量子分组 | 前端二次确认弹窗提示将删除的子分组数量 |
