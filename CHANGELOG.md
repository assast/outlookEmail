# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]

## [2.5.0] - 2026-06-29

### Added
- 分享管理改为表格视图，支持按邮箱搜索、按状态筛选、按邮箱/状态/有效期/创建时间排序。
- 分享管理新增单个删除、批量取消和批量删除能力，对应新增分享删除与批量操作 API。
- 账号列表标签 pill 新增悬停移除入口，可直接从邮箱账号上移除标签。

### Fixed
- 临时邮箱列表复用标签摘要时不再显示账号标签移除入口，避免误调用账号标签接口。

## [2.4.0] - 2026-06-29

### Added
- 账号列表搜索关键字、搜索范围、排序方式和标签筛选现在会保存在浏览器本地，下次打开或切换分组后自动恢复。

### Changed
- 账号搜索范围默认改为“当前分组”，避免默认跨全部分组搜索造成误判。
- Outlook 自动化授权列表不再向前端回显上传密码，只展示密码是否存在和掩码长度。
- Outlook 上传账号模块纳入前端资源哈希，发布后浏览器会自动刷新该模块缓存。
- 清理旧版 Graph OAuth 对比、实现和 Token 提取迁移文档，保留当前测试指南与 API 文档。

### Fixed
- 修复 Graph OAuth 登录过程中跟随 localhost 回调重定向导致无法稳定提取授权码的问题。
- 修复 Docker 构建示例中的在线更新容器名与默认 compose 服务名不一致的问题。

### Security
- 外部 API 上传的 Outlook 暂存密码改为 Fernet 加密存储，授权成功后清空暂存密码。

## [2.3.2] - 2026-06-28

### Changed
- 首页和邮箱分享页在没有用户保存主题时默认使用浅色主题，不再跟随系统深色偏好。

## [2.3.1] - 2026-06-28

### Changed
- 首页 CSS 和 JavaScript 资源 URL 增加内容哈希版本参数，发布后浏览器会自动刷新前端资源缓存。
- 首页 HTML 响应改为禁止缓存，避免升级后继续加载旧入口页面。

### Fixed
- 修复内置 Editorial 皮肤使用固定缓存标识导致 CSS 更新后不生效的问题。

## [2.3.0] - 2026-06-28

### Added
- 新增系统皮肤管理功能，支持通过 API 上传、切换、删除自定义皮肤（CSS 主题），皮肤配置存储在 `data/skins/` 目录下。
- 新增皮肤管理相关 API 端点：上传皮肤、获取当前皮肤、切换皮肤、删除皮肤、重置为默认皮肤。
- 新增皮肤示例文件（`docs/skin-example/skin.json`、`docs/skin-example/theme.css`）和皮肤开发文档（`docs/skins.md`）。
- 新增暗色/亮色主题切换功能，支持系统偏好自动检测和手动切换，状态持久化到 localStorage。
- 新增账号列表刷新按钮，支持从当前分组标题栏一键刷新账号列表，带旋转动画反馈。
- 导航栏新增独立的设置按钮、退出按钮和 GitHub 链接图标按钮（桌面端），替换原有的下拉菜单整合布局。
- 新增 `editorial.css` 皮肤文件，提供 Editorial 风格的排版和配色方案。
- 浏览器扩展 popup 和 sidepanel 重新设计为暗色主题，引入 Plus Jakarta Sans 字体和渐变按钮风格。
- 注：如果发现配色很奇怪，请清理下浏览器缓存
### Changed
- 导航栏布局重构：GitHub Star 按钮迁移为导航栏图标按钮，操作菜单拆分为桌面端独立图标按钮 + "更多功能"下拉菜单，移动端保留原菜单布局。
- 邮件列表刷新按钮改为 SVG 图标 + 旋转动画，替换原文字切换显示方式。
- 分组面板"添加分组"按钮和授权按钮替换为 SVG 图标，统一视觉风格。
- 账号面板工具栏、邮件列表、模态框、Toast 等组件适配皮肤变量，支持自定义主题覆盖。
- 设置页新增皮肤管理界面，支持上传、预览、切换和删除皮肤。

### Fixed
- 修复账号列表刷新按钮在没有选中分组时错误显示的问题，改为仅在选中分组时显示。

## [2.2.0] - 2026-06-27

### Added
- 邮件转发新增并行执行模式，支持同时扫描多个邮箱账号，可配置并行 worker 数量（1-10）。
- 转发轮询间隔改为秒级精度（20-3600 秒），替换原分钟级间隔，保留向后兼容。
- 邮箱分享页面用户 pill 支持点击复制邮箱地址，新增 Toast 提示。
- 并行模式下自动忽略账号间隔，串行模式下保留原有间隔行为。
- 转发调度新增 `forwarding_run_lock` 防止并发执行。

### Changed
- 重构 `process_forwarding_job` 为模块化架构，提取数据库连接、账号解密、任务配置构建、渠道发送等独立函数。
- 浏览器扩展侧边栏设置页同步适配转发秒级间隔、执行模式、并行 worker 配置。
- 设置页转发配置 UI 改为秒级间隔输入、执行模式选择、并行 worker 输入，模式切换时自动联动禁用/启用相关控件。

## [2.1.0] - 2026-06-27

### Added
- 新增邮箱分享功能，支持为单个邮箱账号创建限时或永不过期的只读分享链接。
- 新增分享管理入口，可查看、复制和取消已创建的邮箱分享链接。
- 被分享方通过浏览器打开链接后，只能只读查看该邮箱的收件箱和垃圾邮件，支持邮件列表、邮件详情，暂不支持附件信息展示。

### Changed
- 邮件详情读取逻辑复用为账号级 helper，供登录态页面和匿名分享页面使用。

## [2.0.75] - 2026-06-25

### Fixed
- 修复 Cloudflare 自动导入邮箱的流式进度请求在生产环境中丢失 Flask 应用上下文后返回 500 的问题。

## [2.0.74] - 2026-06-25

### Added
- 邮箱账号面板新增极简展示模式，可隐藏备注、标签、刷新状态等辅助信息以提升列表密度。
- 桌面端分组栏新增折叠/展开控制，并记住用户上次选择的折叠状态。

### Changed
- 优化账号面板工具按钮图标展示，替换部分 emoji 按钮为一致的 SVG 图标。

### Fixed
- 修复未匹配路由等 HTTP 异常被全局异常处理器错误转换为 500 的问题，保留原始 HTTP 状态码。

## [2.0.73] - 2026-06-25

### Added
- Cloudflare 临时邮箱导入支持自动识别并兼容旧格式 `邮箱----JWT`，自动提取邮箱部分，无需手动修改旧导出文件。
- Cloudflare 渠道设置新增"测试连接"功能，支持一键测试域名列表、地址列表和邮件列表三项管理员 API，并展示详细测试结果。
- 新增Cloudflare 自动导入邮箱功能，支持实时进度显示，使用 Server-Sent Events 流式推送导入进度、百分比和统计信息。

### Changed
- 自动导入大数据量时在界面实时显示：已导入数量/总数量 (百分比) - 新增、更新、跳过统计。
- 优化 Cloudflare 导入用户体验，提供平滑的旧格式迁移路径和可见的导入进度。

## [2.0.72] - 2026-06-19

### Changed
- 临时邮箱生成弹窗改为 Cloudflare、GPTMail、DuckMail 分段切换布局，并优化 Cloudflare 渠道、域名、数量、用户名生成方式和标签绑定控件。
- 设置页临时邮箱配置顺序调整为 Cloudflare、GPTMail、DuckMail，并同步侧边导航与前端测试契约。

### Added
- DuckMail 临时邮箱创建表单新增密码显示/隐藏按钮。

## [2.0.71] - 2026-06-19

### Added
- Cloudflare 临时邮箱新增批量生成入口，支持按数量创建、部分失败明细和为成功创建的邮箱自动绑定标签。
- Cloudflare 临时邮箱新增 AI 用户名生成配置，支持 OpenAI-compatible API、保存前测试生成，以及在生成弹窗中显式生成并编辑用户名列表。

### Changed
- Cloudflare 临时邮箱生成弹窗改为多行用户名输入，一行一个；提交创建时只使用显式用户名列表或随机用户名，不再在创建阶段隐式调用 AI。
- Cloudflare 临时邮箱导入保留标签选择，并在界面示例中展示 `[cloudflare:<channel_name>]` 分段和 `邮箱----JWT----渠道名` 写法。

### Fixed
- 修复设置页同一分区包含多个面板时桌面布局错位的问题。

## [2.0.70] - 2026-06-18

### Added
- 分组管理新增最多三级的树形层级，支持创建、编辑、折叠展开、同级排序和跨层级拖拽移动分组。
- 添加/编辑分组弹窗新增父分组选择，分组下拉、批量移动、导出选择和浏览器扩展导出均适配树形展示。

### Changed
- 选中分组时，账号列表、账号搜索、分组导出、全部分组导出和项目分组范围会包含该分组及其所有子分组账号。
- 子分组未配置代理时会向上继承父级分组代理；账号级代理仍优先于分组代理。
- 删除含子分组的分组时会级联删除子分组，并将所有相关账号移回默认分组。

### Fixed
- 外部 API 的 `group_id` 账号筛选保持直接分组语义，避免树形分组升级后改变既有对外 API 范围。
- 分组导出在同时选择父子分组时会去重账号，避免重复导出子分组账号。

## [2.0.69] - 2026-06-15

### Fixed
- 修复 Microsoft Graph 附件元数据查询因选择不支持的 `contentId` 字段导致附件列表获取失败的问题。
- 修复 Graph 邮件详情在附件元数据为空时丢失 `has_attachments` 标记的问题，确保本地保留缓存能识别附件元数据不完整并回源补齐。
- 修复普通邮箱详情请求未稳定携带 `id_mode` 的问题，避免 Graph、UID 和 sequence 消息 ID 语义混用导致详情或附件读取失败。

## [2.0.68] - 2026-06-14

### Fixed
- 修复普通邮箱本地保留详情在缓存标记有附件但附件元数据为空时直接返回本地缓存，导致邮件详情不展示附件的问题；现在会回退远程详情补齐附件元数据并回填本地缓存。

## [2.0.67] - 2026-06-08

### Added
- Token 刷新管理邮箱列表新增分页控件，支持切换每页 100 到 10000 项、上一页/下一页和页码跳转，并记住用户选择的每页数量。

### Changed
- `/api/accounts/refresh-status-list` 的 `page_size` 上限从 500 提升到 10000，前端列表摘要改为显示当前页项目范围。

## [2.0.66] - 2026-06-08

### Added
- Token 刷新管理邮箱列表完整移植普通邮箱列表批量操作，支持选择模式、行点击、`Shift` 连选、拖拽选择，以及刷新 Token、复制邮箱+别名、导出、转发开关、代理、标签、移动分组和删除。

### Changed
- Token 刷新管理中的批量账号变更会同步刷新 Token 列表、主邮箱账号列表、分组计数和相关前端缓存，避免两个列表状态不一致。

## [2.0.65] - 2026-06-07

### Added
- Outlook OAuth 账号新增重新授权入口，支持从编辑账号弹窗和刷新失败提示中更新已有账号授权并自动触发单账号刷新验证。
- 新增 `POST /api/accounts/<account_id>/reauthorize` 接口，只更新已有账号授权字段并保留邮箱、密码、分组、代理、标签等业务信息。

### Fixed
- 重新授权保存新授权信息后先提交数据库事务，再执行自动刷新验证，避免外部刷新请求期间持有 SQLite 写锁。

## [2.0.64] - 2026-06-07

### Added
- Cloudflare Temp Email 新增多渠道管理，支持为多套 Worker、管理员密码和独立邮件池分别配置渠道。
- 设置页新增 Cloudflare 渠道列表与创建、编辑、启用/停用、删除能力，并展示渠道引用数量。
- Cloudflare 临时邮箱创建、读信、删除和全部邮件视图支持按渠道执行；全部邮件入口按渠道独立展示。
- Cloudflare 临时邮箱导入导出支持 `[cloudflare:<channel_name>]` 分段格式，旧格式继续落到默认渠道。

### Changed
- 旧单渠道 Cloudflare 配置会在启动时迁移为默认渠道，已有 Cloudflare 临时邮箱会自动绑定默认渠道。
- Cloudflare 渠道邮箱域名改为可选；未配置域名时渠道仍可保存，域名查询返回空列表。
- `/api/cloudflare/messages` 未传 `channel_id` 时改为使用默认 Cloudflare 渠道。
- Cloudflare 渠道名按大小写不敏感规则保持唯一，旧大小写冲突数据会在迁移时自动重命名后出现的重复项。

### Fixed
- 修复 Cloudflare 渠道表单“新建渠道”按钮实际只清空表单导致误操作的问题。
- 修复 Cloudflare 全部邮件入口重复展示渠道名的问题。

## [2.0.63] - 2026-06-04

### Added
- 新版本提示弹框改为在检测到远端新版本时展示，并显示最近 3 次更新记录。
- 新版本弹框新增“前往下载”和 Docker 在线更新入口；未启用 Docker 在线更新时保留配置说明。

### Changed
- 版本状态接口新增远端更新说明解析，优先从远端 `CHANGELOG.md` 提取最近 3 个版本小节，并保留原有 `release_notes.items` 兼容字段。
- 新版本提示按远端最新版本去重，不再在用户已经更新后按当前运行版本弹出。

## [2.0.62] - 2026-06-04

### Changed
- 重构编辑邮箱账号弹窗布局，将基础信息、认证信息、代理设置、备注与别名分区展示，减少长表单滚动。
- 编辑账号弹窗在桌面端改为更宽的紧凑两列布局，并在移动端自动回退为单列。
- 别名提示文案改为“API 可用别名查询”，避免误解为仅对外 API 支持别名。

## [2.0.61] - 2026-06-04

### Added
- 账号编辑页新增账号密码和 IMAP 密码展示二次验证，已保存密码默认隐藏，仅在输入当前登录密码后显示。

### Changed
- `GET /api/accounts/<id>` 不再返回账号密码和 IMAP 密码明文，只返回 `has_password` / `has_imap_password` 标记；查看密码必须调用 `/api/accounts/<id>/secrets` 并完成登录密码二次验证。
- Web 端账号密码展示入口改为输入框内的小眼睛按钮，验证弹窗会覆盖在编辑弹窗上方，验证后可直接在原编辑弹窗查看密码。
- 浏览器扩展账号编辑页适配密码隐藏逻辑，未填写密码时保留已保存密码。

### Fixed
- 修复账号编辑时省略 `password` 或 `imap_password` 字段会清空已保存密码的问题。

## [2.0.60] - 2026-06-01

### Fixed
- 修复 macOS DMG 安装的桌面应用打开后缺少可用退出入口的问题；macOS 打包运行时现在复用可控桌面服务，并可通过状态栏菜单退出时停止后台服务。

## [2.0.59] - 2026-06-01

### Added
- 新增 macOS DMG 安装包构建脚本，支持生成可拖拽安装的 `OutlookEmail.app` 安装包。
- GitHub Release 工作流新增 macOS x64 和 arm64 安装包产物，并在上传前校验二进制架构。

### Changed
- 搜索框保留多行输入能力，但默认展示高度收敛为一行，并缩小、压缩占位提示文案。
- PyInstaller 打包配置在 macOS 下改为 `.app` bundle，Windows `exe` 构建保持原有 onefile 行为。

## [2.0.58] - 2026-06-01

### Added
- 账号搜索支持空格或换行分隔多个关键词，任一关键词命中主邮箱、别名邮箱、备注或标签即返回结果。
- 搜索框改为多行输入，便于批量粘贴邮箱或关键词，并限制最多 `200` 个唯一关键词。

### Changed
- `/api/accounts/search` 的 `q` 参数改为多关键词 OR 搜索语义，并在超过关键词上限时返回明确错误。
- 临时邮箱列表搜索复用多关键词匹配逻辑，并保持 Cloudflare 全局入口大小写不敏感。
- API 文档同步说明多关键词搜索规则和数量上限。

## [2.0.57] - 2026-05-29

### Added
- 新增账号级代理配置，普通邮箱账号可单独设置主代理、回退代理 1 和回退代理 2。
- 邮箱账号批量操作栏新增“代理”，支持为已勾选账号批量设置或清空账号级代理。
- `/api/accounts/batch-update-proxy` 支持批量设置账号级代理，导入和更新账号接口也支持账号级代理字段。

### Changed
- 邮箱读取、Token 刷新、附件、删除和转发抓信等普通邮箱链路现在优先使用账号级代理；账号代理为空时继续继承分组代理。
- 编辑账号弹窗新增账号代理输入项，代理错误提示改为同时指向账号代理和分组代理。
- API 文档补充账号级代理字段、批量代理接口和代理继承优先级。

### Fixed
- 修复批量代理设置弹窗内触发二次确认时，确认弹窗被代理设置弹窗遮挡的问题。

## [2.0.56] - 2026-05-29

### Added
- 邮箱账号批量操作栏新增“导出”，可在按标签、搜索或当前列表筛选后直接导出已勾选的普通邮箱账号。
- `/api/accounts/export-selected` 支持通过 `account_ids` 导出指定账号，同时保留原有 `group_ids` 导出选中分组能力。

### Changed
- 导出二次验证流程复用现有安全确认弹窗，并根据来源自动提交选中账号或选中分组。
- API 文档、README 和排障文档补充选中账号导出说明。

## [2.0.55] - 2026-05-29

### Added
- 新增普通邮箱本地保留功能，可将 Outlook/Hotmail、OAuth IMAP 回退链路和标准 IMAP 的普通邮箱列表元数据与已读取正文缓存到本机 SQLite。
- 普通邮箱列表支持本地优先渲染，随后后台同步远程 Graph/IMAP 数据；同步发现新邮件时显示非打断式提示，并可在用户确认后合并到当前列表。
- 邮件详情支持优先读取本地保留正文，远程详情读取成功后自动回填正文缓存，远程失败时可回退展示已缓存正文。
- 新增普通邮箱本地保留设置项、存储统计、清理状态和清理缓存操作。
- 新增 `/api/emails/retain-bodies`、`/api/settings/normal-mail-retention/status` 和 `/api/settings/normal-mail-retention/clear` 接口。
- 新增 `docs/local-mail-retention.md`，说明普通邮箱本地保留范围、同步行为、详情正文保留、清理策略和阶段限制。

### Changed
- 普通邮箱列表、详情、标记已读和删除操作会同步维护本地保留状态，保留数据默认受 `normal_mail_local_retention_enabled=false` 开关控制。
- Outlook/Hotmail OAuth 的 IMAP 回退详情和附件下载支持 `id_mode=uid|sequence`，默认按 UID 读取，避免 UID 与序列号混用。
- 普通邮箱关键词过滤会优先检查已缓存正文，只有需要远程详情时才补走远程读取。
- 普通邮箱分页参数改为安全解析，非数字使用默认值、负数按 `0` 处理，远程列表 `top` 最大为 `50`。
- 设置页展示普通邮箱本地保留的已保存邮件数、已缓存正文数、估算保留大小和 SQLite 数据库大小，并在关闭保留开关时提示确认清理。
- README、本地保留说明和 API 文档补充普通邮箱本地保留、正文补齐、清理状态、`id_mode` 和附件下载行为。

### Fixed
- 修复刷新日志、转发日志等接口分页参数未做边界保护时可能因非法输入报错或请求过大分页的问题。
- 修复外部 API Key 比较未做稳定字符串规范化和常量时间比较的问题。
- 修复普通邮箱本地保留重复消息在不同 `id_mode` 下可能影响列表去重、详情回填和刷新查询的问题。
- 修复清理普通邮箱本地保留缓存遇到短暂 SQLite 锁时缺少有限重试，重复清理请求可能启动多个清理任务的问题。
- 修复普通邮箱本地保留列表在分页后才应用主题、发件人和关键词过滤，导致匹配邮件位于后续页时首屏漏显、`count` 和 `has_more` 不准确的问题。
- 修复本地保留列表显示期间后台同步插入新邮件后继续加载更多可能因 offset 漂移而重复或跳过邮件的问题。
- 修复清理或关闭普通邮箱本地保留后，前端内存缓存仍可能继续显示已清理本地邮件列表的问题。

## [2.0.54] - 2026-05-23

### Added
- 新增 Chrome / Edge 浏览器扩展，支持在侧边栏使用邮箱、导入、刷新、Token、导出、标签和设置等常用功能。
- 新增浏览器扩展密码登录桥接接口 `/api/extension/login` 和一次性登录跳转 `/extension-login/<token>`，扩展可使用 Web 登录密码建立正常 Web Session。
- 首页新增版本更新提示弹框，用户更新后首次打开界面会看到本版本新增功能说明，且每个版本只提示一次。

### Changed
- README 增加浏览器扩展入口说明，并将完整发版流程收敛到 `RELEASE.md`。
- API 文档补充浏览器扩展密码登录流程。

## [2.0.53] - 2026-05-21

### Added
- 邮箱账号列表新增批量选择模式，支持点击「☑」后通过账号行选择、多选框选择、`Shift` 连续范围选择和拖拽选择批量勾选账号。

### Changed
- PC 端邮箱账号批量操作菜单改为悬浮在第一个选中账号右侧，并随账号列表滚动重新定位，减少底部空间占用。
- README 补充批量选择、拖拽选择、批量菜单和邮件批量操作的详细使用说明。

### Fixed
- 批量选择手势初始化增加函数存在性保护，避免旧页面状态或脚本加载顺序异常时阻断首页初始化。
- 修复批量选择模式下从账号选择框按住拖拽无法连续选择的问题，并补充 Mac 触控板拖拽选择排查说明。

## [2.0.52] - 2026-05-20

### Added
- 导入邮箱账号支持在不改变账号文本格式的前提下，统一设置新增账号的备注、标签和状态。

### Changed
- 重构导入邮箱账号弹窗的 PC 端布局，将账号信息与导入设置分为两栏展示。
- 导入标签下拉支持点击下拉外部区域自动关闭。

## [2.0.51] - 2026-05-19

### Fixed
- 修复自定义 IMAP 邮件列表首屏误判没有下一页的问题，确保下拉触底能继续触发分页加载，并补充分页边界回归测试。

## [2.0.50] - 2026-05-19

### Changed
- 设置弹层左侧“设置导航”在桌面宽度下支持独立滚动，避免设置项增多时导航超出一屏。

## [2.0.49] - 2026-05-19

### Changed
- WebDAV 备份设置页将“测试 WebDAV”按钮移动到 URL、用户名、密码配置区域旁，减少测试连接时跨屏操作。
- WebDAV 目录 URL 提示补充“需先创建目录”的说明，并给出坚果云 `mailBackup` 示例路径。

### Fixed
- 修复 Outlook Refresh Token 遇到 `AADSTS70000` scope 未授权/过期响应时未继续回退到旧 `.default` 或无 scope 刷新方式的问题。
- Outlook Refresh Token 在 Graph 刷新失败后会继续尝试 IMAP OAuth 刷新，并保存 IMAP 返回的轮换 `refresh_token`。
- WebDAV 测试和手动上传遇到 HTTP 404/409 时会返回可操作的目录创建和路径检查提示，避免只显示状态码。

## [2.0.48] - 2026-05-18

### Fixed
- 修复部分 Outlook Refresh Token 在 `.default` Graph scope 下刷新失败并返回 `AADSTS90023` 的问题；Graph token 获取现在优先使用授权时的显式委托 scope，并在刷新检测中保留无 scope 兼容回退。

## [2.0.47] - 2026-05-18

### Added
- Cloudflare Temp Email 新增“Cloudflare所有邮件”视图，可通过管理员接口查看 Worker 全部邮件，并支持按收件地址过滤和触底分页加载。
- 邮件查询支持 `gmail.com` 与 `googlemail.com` 后缀互相回退；当原地址未命中时，会自动尝试另一个后缀。

### Changed
- Cloudflare 所有邮件列表复用现有邮件列表详情渲染，并在列表中展示收件地址和来源标识。
- 邮件查询响应新增稳定的 `resolved_query_email`、`fallback_used`、`fallback_email` 字段，用于说明实际命中的查询地址。

## [2.0.46] - 2026-05-14

### Added
- 邮箱列表搜索框新增范围选择，可在“所有分组”和“当前分组”之间切换筛选范围。
- 账号搜索接口 `/api/accounts/search` 新增可选 `group_id` 参数，支持仅搜索指定分组下的账号。

### Changed
- 当前分组搜索结果标题会标明分组范围，全局搜索结果继续展示账号所属分组信息。

## [2.0.45] - 2026-05-12

### Added
- 邮件详情新增“显示邮件源”入口，可按需查看原始 MIME 邮件源码。
- 原始邮件查看器支持复制源码和下载 `.eml` 文件，并提示完整邮件头包含敏感路由信息。
- 后端新增 `/api/email/<email>/<message_id>/raw` 接口，支持 Graph `$value`、Outlook IMAP `RFC822` 和自定义 IMAP 账号获取邮件源。

### Changed
- 邮件详情工具栏将信任模式文案恢复为“信任此邮件”，并将原始邮件入口命名为“显示邮件源”。

## [2.0.44] - 2026-05-08

### Added
- 邮箱列表新增服务端分页参数和滚动加载，单页条数最高支持 `10000`。
- 邮箱列表支持在服务端按标签筛选，并返回 `total`、`offset`、`limit` 和 `has_more` 分页状态。

### Changed
- 普通邮箱批量导入改为单事务批量写入，提升万级账号导入性能，并返回新增、跳过重复和无效行数量。
- 邮箱列表加载改为批量预载标签和别名，并新增常用账号查询索引，降低大列表查询开销。
- 标签筛选和单页条数控制压缩为同一行展示，批量选择文案改为面向“已加载”账号。

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
