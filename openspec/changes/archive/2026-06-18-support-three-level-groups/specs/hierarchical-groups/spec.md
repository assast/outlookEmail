## ADDED Requirements

### Requirement: 三级分组数据模型
系统 SHALL 支持 `groups` 表存储最多 3 级的树形层级关系。每个分组 MUST 有 `parent_id`（可 NULL）和 `level`（1/2/3）字段。`level=1` 的分组 `parent_id` MUST 为 NULL。

#### Scenario: 创建一级分组
- **WHEN** 用户创建分组且未指定父分组
- **THEN** 系统创建 `level=1, parent_id=NULL` 的分组

#### Scenario: 创建二级分组
- **WHEN** 用户创建分组并指定父分组为一级分组
- **THEN** 系统创建 `level=2, parent_id=父分组id` 的分组

#### Scenario: 创建三级分组
- **WHEN** 用户创建分组并指定父分组为二级分组
- **THEN** 系统创建 `level=3, parent_id=父分组id` 的分组

#### Scenario: 禁止创建超过三级
- **WHEN** 用户尝试在三级分组下创建子分组
- **THEN** 系统 SHALL 拒绝并提示"已达到最大层级深度"

### Requirement: 递归后代分组查询
系统 SHALL 提供函数 `get_descendant_group_ids(group_id)` 返回指定分组的所有后代分组 ID 列表（含自身）。

#### Scenario: 一级分组递归查询
- **WHEN** 查询一级分组 `A`（含二级子分组 `B`、`C`，其中 `B` 含三级子分组 `D`）的后代
- **THEN** 返回 `[A.id, B.id, D.id, C.id]`

#### Scenario: 叶子分组递归查询
- **WHEN** 查询三级叶子分组的后代
- **THEN** 仅返回 `[自身id]`

### Requirement: 递归账号展示
选中任意分组时，系统 SHALL 在账号面板中展示该分组及所有后代分组下的账号。

#### Scenario: 选中一级分组查看递归账号
- **WHEN** 用户选中一级分组 `客户A`（有二级子分组`项目1`、`项目2`，其中`项目1`有三级子分组`子类1`）
- **THEN** 账号面板展示 `客户A`、`项目1`、`项目2`、`子类1` 下的账号

#### Scenario: 选中二级分组查看递归账号
- **WHEN** 用户选中二级分组（有三级子分组）
- **THEN** 账号面板展示该二级分组及其三级子分组下的账号

### Requirement: 代理配置级联回退
子分组未设置代理时，系统 SHALL 向上回退到父分组的代理配置，直到找到有代理的祖先分组或到达根节点。

#### Scenario: 三级分组代理回退
- **WHEN** 三级分组未设代理、其父二级分组设了代理 `http://proxy:8080`
- **THEN** 该三级分组下账号的代理配置为 `http://proxy:8080`

#### Scenario: 全链回退
- **WHEN** 三级分组及父二级分组均未设代理、祖父一级分组设了代理
- **THEN** 账号代理继承祖父一级分组的代理配置

#### Scenario: 无任何祖先代理
- **WHEN** 三级分组、父二级、祖父一级均未设代理
- **THEN** 账号代理配置为空值

### Requirement: 级联删除分组
删除含有子分组的分组时，系统 SHALL 级联删除所有子分组，并将所有被删除分组（含子分组）下的账号移回默认分组 (id=1)。

#### Scenario: 删除含子分组的分组
- **WHEN** 用户删除一级分组 `客户A`（下有二级分组 `项目1`、`项目2`）
- **THEN** `项目1`、`项目2` 被删除，它们下面所有账号的 `group_id` 设为 `1`（默认分组），`客户A` 被删除

#### Scenario: 不允许删除默认分组
- **WHEN** 用户尝试删除默认分组 (id=1)
- **THEN** 系统 SHALL 拒绝删除

#### Scenario: 不允许删除临时邮箱分组
- **WHEN** 用户尝试删除临时邮箱分组
- **THEN** 系统 SHALL 拒绝删除

### Requirement: 临时邮箱分组限制
临时邮箱分组 (`is_system=1`) SHALL 始终为一级根分组，不允许在其下创建子分组，也不允许将其移动为其他分组的子分组。

#### Scenario: 阻止在临时邮箱下创建子分组
- **WHEN** 用户尝试指定临时邮箱分组为父分组创建子分组
- **THEN** 系统 SHALL 拒绝并提示错误

#### Scenario: 阻止移动临时邮箱分组
- **WHEN** 用户尝试将临时邮箱分组拖拽到其他分组下
- **THEN** 系统 SHALL 拒绝该操作

### Requirement: 跨层级移动分组
系统 SHALL 支持通过拖拽将分组移动到不同父级下，移动时 MUST 校验目标深度与子树深度之和不超过 3。

#### Scenario: 将二级分组移到另一个一级分组下
- **WHEN** 用户将二级分组 `项目1` 从一级分组 `客户A` 拖到一级分组 `客户B` 下
- **THEN** `项目1` 的 `parent_id` 更新为 `客户B.id`，`level` 保持 2，其子分组 level 不变

#### Scenario: 将一级分组移为另一分组的子分组
- **WHEN** 用户将一级分组 `X`（无子分组）拖入一级分组 `Y` 下
- **THEN** `X` 的 `parent_id` 设为 `Y.id`，`level` 更新为 2

#### Scenario: 移动导致超过三级深度时拒绝
- **WHEN** 用户将含二级子分组的一级分组拖入另一个二级分组下
- **THEN** 系统 SHALL 拒绝并提示"移动后层级深度将超过 3 级"

### Requirement: 同父级下排序
系统 SHALL 支持在同一 `parent_id` 下通过 `sort_order` 对子分组排序。

#### Scenario: 同级排序
- **WHEN** 用户拖拽调整同一父分组下两个子分组的顺序
- **THEN** 系统更新它们的 `sort_order` 使顺序与拖拽结果一致，不影响其他父级下的分组

### Requirement: 分组名称全局唯一
分组名称 SHALL 在全局范围内保持唯一，不区分同 parent 或不同 parent。

#### Scenario: 创建同名分组被拒绝
- **WHEN** 用户尝试创建与已存在分组同名的分组（即使在不同父级下）
- **THEN** 系统 SHALL 拒绝并提示"分组名称已存在"

### Requirement: 后代账号数统计
系统 SHALL 提供分组的后代账号数统计（含直属及所有递归后代的账号）。

#### Scenario: 一级分组的后代账号数
- **WHEN** 一级分组 `客户A` 直属 3 个账号，二级子分组 `项目1` 有 5 个账号，`项目2` 有 2 个账号
- **THEN** `客户A` 的 `descendant_account_count` 为 10

#### Scenario: 叶子分组的后代账号数
- **WHEN** 三级叶子分组有 5 个直属账号
- **THEN** 其 `descendant_account_count` 为 5

### Requirement: 数据库迁移兼容
系统 SHALL 提供迁移脚本为已有扁平分组数据补充 `parent_id=NULL, level=1`。

#### Scenario: 已有分组迁移
- **WHEN** 数据库从扁平结构升级
- **THEN** 所有已有分组的 `parent_id` 为 NULL、`level` 为 1，功能不受影响
