# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]

## [2.0.43] - 2026-05-08

### Added
- Token 刷新管理新增当前列表选择、清空选择、刷新已选和删除已选批量操作。
- 新增选中账号流式刷新任务接口：先通过 `POST /api/accounts/refresh-selected-stream` 初始化任务，再通过返回的 `stream_url` 订阅 SSE 进度。

### Changed
- Token 刷新管理里的“刷新已选”不再把 `account_ids` 放入 SSE GET query，改为 POST 初始化任务后再订阅任务流。
- 部署文档明确服务需保持单 worker 运行；官方 Docker 镜像继续使用 Gunicorn 单 worker + 多线程模式。

### Fixed
- 批量删除账号后会同步刷新 Token 刷新管理列表、主账号列表和相关本地缓存，避免界面仍显示已删除账号。

## [2.0.42] - 2026-05-07

### Added
- 系统设置新增“展示组ID”开关，可统一控制分组列表、账号摘要等位置的分组 ID 徽标显示。
- 首页版本按钮在检测到仓库存在更高版本时，会显示与版本按钮共用点击入口的升级箭头提示图标。

### Changed
- 设置页将登录密码和对外 API Key 归入“常规设置”，并把 GPTMail、DuckMail、Cloudflare 三个临时邮箱设置统一移动到设置页底部。
- 首页升级提示由文字改为向上箭头图标，并沿用 GitHub Star 徽标的金色配色风格。
- 版本弹层补充说明：仅 Docker 版本支持在线更新，并引导查看 README 中的对应配置文档。

### Fixed
- 修复首页版本升级提示在版本一致时仍然显示的问题，补充 `hidden` 状态下的样式兜底，仅在当前版本低于仓库版本时显示升级图标。

## [2.0.41] - 2026-05-06

### Fixed
- 修复 Docker 在线更新在较新的 Docker daemon 上因 API 版本过旧而无法获取容器状态的问题；当 daemon 明确返回最低支持版本时，应用会自动按该版本重试。
- 修复 Docker 在线更新拉起的 Watchtower 容器未继承 Docker API 版本导致检查/更新直接失败的问题。
- 修复 Watchtower 带 ANSI 颜色码的日志摘要无法被正确解析的问题，避免把 `Failed=0 / Updated=0` 的“无需更新”结果误报成更新失败。

## [2.0.40] - 2026-05-06

### Changed
- Docker 在线更新状态新增文件持久化，仅保留最新一次结果；容器自更新重启后，新的进程会恢复最近一次任务状态。
- Docker 在线更新新增独立的 `DOCKER_UPDATE_STATUS_TIMEOUT`，用于状态查询和容器 inspect，避免复用实际更新任务超时。
- 文档补充 Docker 在线更新仅适用于 `latest`、`main`、`dev` 这类可变镜像标签的限制说明。

### Fixed
- 修复 Docker 在线更新在当前容器重启后丢失任务状态的问题，服务重启后会把中断中的任务恢复为“结果未知”的最终状态。
- 修复 Docker 在线更新前端轮询在 `success == null` 时静默结束的问题，改为明确提示“服务可能已重启，请刷新并核对当前版本/镜像”。

## [2.0.39] - 2026-05-06

### Added
- 邮件详情附件区新增“全部下载”，可将同一封邮件的多个附件打包为 ZIP 下载。
- 版本弹层新增 Docker 在线更新入口，可在启用 `DOCKER_UPDATE_ENABLED` 后从界面触发容器更新。
- 新增 `/api/docker-update/status` 与 `/api/docker-update`，用于查询 Docker 更新能力并启动受登录和 CSRF 保护的更新任务。

### Changed
- Docker 在线更新改为通过一次性 Watchtower 容器执行，并为自定义 `DOCKER_UPDATE_SOCKET` 注入对应 `DOCKER_HOST`。
- README 将 Docker 在线更新配置移入可选小节，并提供完整 `docker-compose.yml` 示例，避免默认示例直接挂载 Docker socket。

### Fixed
- 完整读取 Docker pull 响应流并检测 `error` / `errorDetail.message`，避免 Watchtower 镜像拉取失败时误判为更新任务已启动。

## [2.0.38] - 2026-05-03

### Added
- 系统设置新增 WebDAV 备份配置，支持按 5 段 Cron 使用常规设置里的时区计算下次执行时间。
- WebDAV 备份支持测试连接和手动上传；测试仅上传临时测试文件，手动上传会立即上传“导出全部分组”的真实备份文件。

### Changed
- 修改 WebDAV 备份相关设置和手动上传真实备份时需要验证登录密码，降低敏感导出数据被误操作上传的风险。
- “导出选中分组”的生成逻辑抽出复用，WebDAV 备份使用与导出功能一致的全部分组文件格式。

### Fixed
- 修复临时邮箱列表空结果渲染时引用不存在的 `selectedTagIds` 导致保存设置后前端报错的问题。
- 修复设置保存成功后刷新列表失败会误提示“保存设置失败”的问题，改为明确提示设置已保存但列表刷新失败。

## [2.0.37] - 2026-04-29

### Added
- 系统设置新增“展示排序值”开关，可控制普通邮箱列表底部是否显示自定义排序值。

### Changed
- “展示排序值”默认改为关闭；新装或缺省配置下，普通邮箱列表不再默认展示排序值。

### Fixed
- 补齐排序值展示开关的设置持久化、启动恢复、列表即时刷新、API 文档与回归测试。

## [2.0.36] - 2026-04-29

### Fixed
- 转发设置新增“账号间隔”秒级配置，转发轮询在处理多个已开启转发账号时会按配置在账号之间等待，避免短时间连续拉取多个账号。
- 补齐转发账号间隔的设置持久化与回归测试，覆盖设置接口回显以及多个账号之间的等待行为。

## [2.0.35] - 2026-04-29

### Fixed
- 修复切换已缓存邮箱时仍可能触发自动补拉请求的问题，普通邮箱账号切换改为仅展示当前缓存，不再因为列表展示动作隐式刷新下一页。
- 修复 `全部邮件` 缓存派生 `收件箱 / 垃圾邮件` 视图时分页基线错位的问题，新增按 folder 维度的 `fetched_count / has_more / success` 元数据并补充对应回归测试。

## [2.0.34] - 2026-04-28

### Added
- Token 刷新管理新增全量刷新任务日志面板和停止任务按钮，支持在执行期间查看账号级进度与结果。

### Changed
- Token 刷新管理移除“最近一次全量刷新”卡片展示，顶部统计区收敛为总邮箱数、成功邮箱和失败邮箱三项。
- Token 刷新确认框改为叠加展示，触发全量刷新时不再关闭 Token 刷新管理弹窗。
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。

### Fixed
- 修复 Windows 控制台输出 Unicode 符号时触发的编码异常，统一改为编码安全的调度器、转发与错误日志输出。
- 修复调度器退出阶段重复调用 shutdown() 导致的 SchedulerNotRunningError，atexit 回调统一复用幂等的 shutdown_scheduler()，并补充回归测试。
- 修复全量刷新过程中无法保留弹窗上下文的问题，并补充停止任务接口、停止事件回传和相关回归测试。
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
## [2.0.33] - 2026-04-28

### Added
- 账号新增可持久化的自定义排序值 `sort_order`，列表支持按排序值、创建时间或邮箱名查看。
- 系统设置新增“展示创建时间”开关，默认开启；邮箱列表左下角可按应用时区展示账号创建时间。
- Token 刷新管理新增工作台式邮箱列表，支持按邮箱/备注/分组搜索，并按 `全部 / 成功 / 失败 / 从未刷新` 状态筛选。

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 邮箱列表移除“最近刷新”时间展示和对应排序入口，未设置 `sort_order` 时默认回退为按创建时间排序。
- 重构桌面端设置页侧边导航，移除 `Control Center` / 保存提醒卡片，新增置顶“常规设置”分区，并将时区与创建时间展示开关迁入该分区。
- 普通邮箱与临时邮箱列表统一移除序号展示，列表卡片仅保留邮箱主体信息与状态内容。
- Token 刷新状态主读路径收敛为 `accounts + token_refresh_state`，刷新管理弹窗改为“快照 + 筛选 + 邮箱列表”单工作台，并移除独立“失败邮箱 / 刷新历史”区块。
- Token 刷新管理中的邮箱列表进一步收敛为表格视图，统一展示邮箱、分组、最近刷新、状态和操作列。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复账号更新动态覆盖路由未同步透传 `sort_order` 的问题，避免编辑保存后自定义排序失效。
- 统一账号列表、搜索结果和详情接口中的 `sort_order` 返回结构，并补齐对应回归测试。
- 修复邮件转发轮询间隔设置为 `60` 分钟时生成非法 `*/60` Cron 表达式的问题，改为按整点触发并补充对应回归测试。
- 修复全量 Token 刷新异常中止时快照状态误落为 `idle` 的问题，改为正确记录 `failed / partial_failed`，并补记当前账号失败状态。
- 修复全量 Token 刷新可被重复触发的问题，新增后端互斥与前端冲突提示，避免并发任务覆盖同一轮最新快照。
- 恢复 `account_refresh_logs` 半年历史清理，避免刷新日志长期无上限增长，并同步更新刷新相关 API 文档。

## [2.0.32] - 2026-04-24

### Added
- 标签筛选新增“无标签”虚拟项，支持单独筛选未打标签的账号和临时邮箱，并保持与现有标签的 OR 过滤语义。


## [2.0.31] - 2026-04-24

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复内部取邮件接口会误更新账号 `last_refresh_at` 的问题，避免“最近刷新时间”被普通收信动作污染，并补充对应回归测试。


## [2.0.30] - 2026-04-24

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复 Outlook 账号在手动刷新、批量刷新和定时刷新成功后未持久化微软返回的新 `refresh_token` 的问题，避免后续继续使用旧 token 导致 `AADSTS70000 grant is expired` 一类失效报错，并补充对应回归测试。


## [2.0.29] - 2026-04-23

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复多个模态框和全屏邮件详情在背景层点击关闭时的事件时序问题，统一改为在 `mousedown` 阶段处理 backdrop 关闭，减少误触和异常关闭。


## [2.0.28] - 2026-04-22

### Added
- 系统设置新增应用时区选择，支持按保存的时区预览 Cron 下次运行时间，并统一日志与 OAuth 相关时间展示。
- 页面初始化阶段会主动读取 `/api/settings` 恢复全局时区，不再依赖先打开设置弹窗。

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 定时刷新与邮件转发调度器改为基于 `app_timezone` 创建触发器；旧库升级时默认回退到 `Asia/Shanghai`。
- 新增 `main` 推送后自动合并到 `dev` 的 GitHub Actions 工作流，减少发布后分支偏移。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复添加账号流程里误插入的时区更新语句，避免保存账号成功后前端报错。
- 修正设置保存成功提示，明确“时间展示立即生效，定时任务需重启后生效”。
- 补齐前端启动时区加载、非默认时区保存后刷新展示，以及旧库无 `app_timezone` 升级默认行为的回归验证。
- 同步更新 `docs/api.md` 中设置接口的 `app_timezone` 与 `time_zone` 字段说明。


## [2.0.27] - 2026-04-20

### Added
- 邮件列表新增未读状态展示与批量“设为已读”操作，支持在前端选中多封邮件后统一更新已读状态。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复 Docker 部署场景下保存设置或导入邮箱时偶发 `The CSRF session token is missing` 的问题，改为基于当前登录 session 获取不可缓存的 CSRF token，并在前端遇到 CSRF 失配时自动刷新重试一次。
- 修复 Gmail 在 `IMAP (Generic)` 模式下因 `FETCH` 响应分段导致全部邮件长期显示为未读的问题，改为整包解析 IMAP `FLAGS` 与 `INTERNALDATE`。

## [2.0.26] - 2026-04-19

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复桌面端邮件列表滚动到末尾后未继续加载下一页邮件的问题，补强分页偏移计算与列表重渲染后的自动续加载检查。

## [2.0.25] - 2026-04-19

### Added
- 临时邮箱列表新增标签能力，支持展示标签、按标签筛选，以及在临时邮箱分组内批量添加或移除标签。
- 新增临时邮箱批量删除接口与前端选择操作，便于在同一套批量工具栏中统一清理临时邮箱。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复临时邮箱场景下标签系统只支持普通账号的问题，补齐临时邮箱的数据库关联、接口返回和前端搜索联动。
- 为临时邮箱标签接口补充后端回归测试，覆盖标签回显以及批量加减标签流程。

## [2.0.24] - 2026-04-19

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复分组排序在应用重启后可能丢失的问题，确保拖拽后的分组顺序可以稳定持久化，并补充对应后端回归测试。
- 修复账号导入弹窗中样例文本的换行展示，避免示例格式被挤成单行后影响批量导入判断。
- 修复桌面端设置页中“按天数”/“Cron 表达式”等选项卡在向下滚动时覆盖“系统设置”标题栏的问题，改为内容区独立滚动并同步调整侧栏联动逻辑。

## [2.0.23] - 2026-04-19

### Added
- 顶部导航新增版本信息展示，支持查看当前版本、复制版本号并跳转到更新日志。

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 调整导航品牌区布局，将版本信息与 GitHub 入口整理为更统一的产品元信息区域。
- 重绘 GitHub Star 按钮样式，改为更贴合当前控制台风格的胶囊按钮，并补充 hover、active、focus 反馈。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复顶部版本信息在部分浏览器环境下点击无响应的问题，改为更稳定的全局触发方式。

## [2.0.22] - 2026-04-17

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复动态覆盖后的 `PUT /api/accounts/<id>`、`GET /api/emails/<email>`、`GET /api/external/emails` 丢失鉴权装饰器的问题，避免未登录或未携带 API Key 时绕过访问控制。
- 为动态路由覆盖增加启动期保护断言，若关键 endpoint 被未包装函数替换会在应用启动时直接报错，防止鉴权再次静默失效。
- 补充外部邮件接口、内部邮件接口、账号更新接口和动态 endpoint 保护标记的回归测试，覆盖实际 401 行为与路由注册状态。

## [2.0.21] - 2026-04-17

### Added
- 为邮件详情增加附件列表展示与下载能力，支持 Graph 和 IMAP 邮箱直接查看并下载邮件附件。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复 IMAP 纯文本邮件详情被错误拼接为带字面量 `<br>` 的正文内容问题，现按纯文本正确返回。

## [2.0.20] - 2026-04-16

### Added
- 左侧账号列表新增“复制邮箱+别名”批量操作，可一次复制所选账号的主邮箱和全部别名邮箱，并自动去重后写入剪贴板。

## [2.0.19] - 2026-04-15

### Added
- 新增内置 `2925邮箱` 类型，默认使用 `imap.2925.com:993`，并补充域名到 provider 的自动识别和前端导入/编辑下拉项。

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- 修复部分自定义 IMAP / 2925 IMAP 服务端无法正确返回 `SEARCH` / `UID SEARCH` 结果时，收件箱明明有邮件却列表为空的问题。
- 为 IMAP 列表与详情查询增加 `UID SEARCH -> SEARCH -> 按 EXISTS 数量直接 FETCH` 的多层回退，兼容实现不标准的服务器。

## [2.0.18] - 2026-04-15

### Added
- 新增项目运行时后端模型，支持按 `project_key` 管理邮箱在项目内的独立状态，并提供启动项目、项目列表、项目账号列表、领取、成功、失败、释放、重置失败、移出项目、恢复项目等完整接口。
- 为项目运行时补充后端回归测试，覆盖启动项目、分组范围补全、失败后需人工重置、删除后重导入同邮箱沿用旧项目状态等关键路径。

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 将“创建项目 + 范围补全”设计收敛为单一“启动项目”语义，重复启动同一项目时只补全新增邮箱，不重置已有项目状态。
- 项目内邮箱身份改为按邮箱地址而不是纯 `account_id` 维护，避免删除后重导入同邮箱绕过既有 `done` / `failed` 状态。

### Documentation
- 补充 `docs/api.md` 中的项目管理接口文档，覆盖状态说明、启动项目语义、查询参数、关键请求/响应示例，以及 `deleted` 与重导入复用规则。

## [2.0.17] - 2026-04-15

### Added
- 新增企业微信群机器人 Webhook 转发渠道，只需填写 Webhook 地址即可作为独立转发通道使用。
- 为企业微信转发补充设置持久化、测试发送和基础回归测试，覆盖设置保存与实际发送调用。

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 修改发布流程，支持推送 `vX.Y.Z` 版本标签后自动触发 GitHub Release 工作流，手动触发改为兜底方案。
- 调整 Docker 构建参数，关闭 provenance / SBOM attestation，避免 GHCR 发布版本额外显示 `unknown/unknown` 平台条目。


## [2.0.16] - 2026-04-15

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- 重构桌面端设置界面，改为更宽的双栏布局，并为主要设置模块增加左侧快速定位导航。
- 为设置导航增加点击定位与滚动联动高亮，减少在长设置表单中来回查找的成本。
- 将“邮件转发设置”压缩为更偏控制台式的紧凑布局，把轮询参数、动作按钮和渠道配置整理为高密度桌面端面板。

### Added
- 为桌面端设置页左侧“当前包含”增加模块级快速跳转入口，支持直接跳到 Access、DuckMail、Cloudflare、刷新策略和邮件转发。
- 为“最近转发历史”和“最近转发失败”增加默认折叠的抽屉式面板，按需展开日志列表，缩短默认页面高度。


## [2.0.15] - 2026-04-15

### 文档
- 新增中文发版说明，补充版本号规则、标准发布流程、GitHub Actions 行为和发版后核对清单。
- 新增升级指南，覆盖 Docker、Windows `exe`、Python 直跑场景的升级、回滚与注意事项。
- 调整 `README.md` 与部署文档中的镜像标签说明和发布流程描述，使其与当前工作流保持一致。

## [2.0.14] - 2026-04-14

### Added
- Added progressive `+suffix` fallback matching for mailbox and alias lookups so internal and external mail APIs can resolve addresses such as `user+work@gmail.com` back to the managed primary mailbox or alias.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed aggregated `folder=all` ordering for IMAP/Gmail mailboxes by normalizing RFC822 timestamps that include trailing timezone labels such as `(UTC)`.
- Fixed IMAP all-mail merging to prefer the server-reported `INTERNALDATE` when available so merged results are sorted by received time instead of unreliable header `Date`.
- Fixed the mobile mail list layout so very long sender addresses no longer push the card outside the viewport, and folder badges now wrap to a new line on narrow screens.

## [2.0.11] - 2026-04-14

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed the manual GitHub release workflow packaging path so Windows release assets and Docker release publication no longer fail during the release run.

## [2.0.10] - 2026-04-13

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Changed `folder=all` mailbox aggregation to fetch `inbox` and `junkemail` in parallel before merging and sorting the result list.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed the aggregated mail path to pass group proxy failover settings consistently to both `inbox` and `junkemail` fetches.
- Fixed the external `/api/external/emails` compatibility check coverage so `folder=all` remains accepted without changing the live API request or response contract.

## [2.0.9] - 2026-04-13

### 新增
- 邮件列表顶部新增“全部邮件”选项，并放在“收件箱”前面。

### 变更
- 选择邮箱账号后默认展示“全部邮件”列表。
- 邮件列表的加载中和空状态文案会根据当前文件夹显示对应名称。

### 修复
- 修复“全部邮件”列表中无法区分邮件来自收件箱还是垃圾邮件的问题，现已显示来源标签。
- 修复从“全部邮件”列表打开邮件详情时仍按 `all` 请求，导致详情可能取错文件夹的问题，现改为按邮件真实来源文件夹加载。

## [2.0.8] - 2026-04-12

### Added
- Added per-group proxy failover settings with `主代理 -> 回退代理 1 -> 回退代理 2` order for Outlook Graph/token requests.

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Moved proxy failover configuration from system-wide settings into each mailbox group so different groups can use different fallback chains.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed Outlook token refresh and Graph requests failing immediately when the primary group proxy was unreachable by retrying through configured fallback proxies in order.
- Fixed the group settings dialog copy to document that `回退代理 1` and `回退代理 2` both support `direct` / `直连` as explicit direct-connect fallbacks.

## [2.0.7] - 2026-04-11

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Replaced the custom Windows tray implementation with a `pystray`-based tray menu and generated application icon.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed the packaged Windows desktop app tray menu labels and icon rendering issues.
- Removed the brittle dependency on low-level Win32 `ctypes` tray bindings that caused repeated Windows-specific startup failures.

## [2.0.6] - 2026-04-11

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed additional Windows tray startup crashes by replacing more `ctypes.wintypes` handle annotations with compatibility-safe Win32 handle definitions.

## [2.0.5] - 2026-04-11

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed the Windows tray bootstrap using unavailable `ctypes.wintypes` symbols (`LRESULT`, `WNDPROC`) that caused the packaged app to crash during startup.

## [2.0.4] - 2026-04-11

### Added
- Added a Windows system tray controller for the packaged desktop app with `打开界面` and `退出` actions.

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Switched the packaged Windows desktop runtime to a controllable background server so the tray can exit the app cleanly.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed the Windows packaged app having no visible way to quit after launching the browser UI.

## [2.0.3] - 2026-04-11

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed Windows `exe` packaging to include Python modules imported from dynamically executed segmented files, preventing startup crashes such as `ModuleNotFoundError: No module named 'imaplib'`.
- Made the PyInstaller hidden-import list derive automatically from the segmented source files so future segment imports are included in packaged builds.

## [2.0.2] - 2026-04-11

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Switched the packaged desktop build to GUI mode and auto-open the local web UI in the browser on startup.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed packaged startup diagnostics so desktop launch failures are written to `startup-error.log` and surfaced to Windows users with a dialog instead of silently exiting.
- Fixed the packaged desktop default bind host to use `127.0.0.1`, avoiding local browser access issues on some Windows machines.

## [2.0.1] - 2026-04-11

### Added
- Added automated Windows `exe` packaging in the tag-based GitHub Release workflow.
- Added a PyInstaller spec and packaged-runtime resource handling for the desktop build.

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Documented the Windows desktop distribution flow in the README, deployment guide, and release guide.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed packaged execution so templates, static assets, database storage, and `SECRET_KEY` persistence work correctly after bundling.

## [2.0.0] - 2026-04-09

### Changed
- Token 刷新管理移除运行中的进度卡片，统一改为在弹窗内持续展示任务日志。
- Formalized the repository into a release-managed project with `main` / `dev` branch roles, semantic versioning, and documented release flow.
- Added automated GitHub Release generation and clarified collaboration / branch-protection guidance for future contributors.
- Tightened Docker image publishing policy so documentation-only changes no longer trigger image builds.

### Added
- Added `VERSION`, `CHANGELOG.md`, `RELEASE.md`, and `BRANCH_PROTECTION.md` to make versioning, release, and collaboration rules explicit.
- Added release-tag driven image/version workflow for `latest`, `dev`, and semantic version tags.

### Fixed
- 修复“重试失败”仍走同步请求的问题，改为流式日志输出并复用刷新间隔与停止任务控制。
- Fixed invalid Docker image tag generation caused by `docker/metadata-action` in tag-triggered builds.

## [1.0.0] - 2026-04-07

### Added
- Stable initial release baseline for the Outlook mail management tool.
- Web UI for mailbox group management, mailbox import, and mail browsing.
- Outlook access via Microsoft Graph API, new IMAP, and legacy IMAP fallback.
- Temporary mailbox integration for GPTMail, DuckMail, and Cloudflare Temp Email.
- External API access using API Key authentication.
- Docker and Docker Compose deployment support.
