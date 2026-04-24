# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]


## [2.0.32] - 2026-04-24

### Added
- 标签筛选新增“无标签”虚拟项，支持单独筛选未打标签的账号和临时邮箱，并保持与现有标签的 OR 过滤语义。


## [2.0.31] - 2026-04-24

### Fixed
- 修复内部取邮件接口会误更新账号 `last_refresh_at` 的问题，避免“最近刷新时间”被普通收信动作污染，并补充对应回归测试。


## [2.0.30] - 2026-04-24

### Fixed
- 修复 Outlook 账号在手动刷新、批量刷新和定时刷新成功后未持久化微软返回的新 `refresh_token` 的问题，避免后续继续使用旧 token 导致 `AADSTS70000 grant is expired` 一类失效报错，并补充对应回归测试。


## [2.0.29] - 2026-04-23

### Fixed
- 修复多个模态框和全屏邮件详情在背景层点击关闭时的事件时序问题，统一改为在 `mousedown` 阶段处理 backdrop 关闭，减少误触和异常关闭。


## [2.0.28] - 2026-04-22

### Added
- 系统设置新增应用时区选择，支持按保存的时区预览 Cron 下次运行时间，并统一日志与 OAuth 相关时间展示。
- 页面初始化阶段会主动读取 `/api/settings` 恢复全局时区，不再依赖先打开设置弹窗。

### Changed
- 定时刷新与邮件转发调度器改为基于 `app_timezone` 创建触发器；旧库升级时默认回退到 `Asia/Shanghai`。
- 新增 `main` 推送后自动合并到 `dev` 的 GitHub Actions 工作流，减少发布后分支偏移。

### Fixed
- 修复添加账号流程里误插入的时区更新语句，避免保存账号成功后前端报错。
- 修正设置保存成功提示，明确“时间展示立即生效，定时任务需重启后生效”。
- 补齐前端启动时区加载、非默认时区保存后刷新展示，以及旧库无 `app_timezone` 升级默认行为的回归验证。
- 同步更新 `docs/api.md` 中设置接口的 `app_timezone` 与 `time_zone` 字段说明。


## [2.0.27] - 2026-04-20

### Added
- 邮件列表新增未读状态展示与批量“设为已读”操作，支持在前端选中多封邮件后统一更新已读状态。

### Fixed
- 修复 Docker 部署场景下保存设置或导入邮箱时偶发 `The CSRF session token is missing` 的问题，改为基于当前登录 session 获取不可缓存的 CSRF token，并在前端遇到 CSRF 失配时自动刷新重试一次。
- 修复 Gmail 在 `IMAP (Generic)` 模式下因 `FETCH` 响应分段导致全部邮件长期显示为未读的问题，改为整包解析 IMAP `FLAGS` 与 `INTERNALDATE`。

## [2.0.26] - 2026-04-19

### Fixed
- 修复桌面端邮件列表滚动到末尾后未继续加载下一页邮件的问题，补强分页偏移计算与列表重渲染后的自动续加载检查。

## [2.0.25] - 2026-04-19

### Added
- 临时邮箱列表新增标签能力，支持展示标签、按标签筛选，以及在临时邮箱分组内批量添加或移除标签。
- 新增临时邮箱批量删除接口与前端选择操作，便于在同一套批量工具栏中统一清理临时邮箱。

### Fixed
- 修复临时邮箱场景下标签系统只支持普通账号的问题，补齐临时邮箱的数据库关联、接口返回和前端搜索联动。
- 为临时邮箱标签接口补充后端回归测试，覆盖标签回显以及批量加减标签流程。

## [2.0.24] - 2026-04-19

### Fixed
- 修复分组排序在应用重启后可能丢失的问题，确保拖拽后的分组顺序可以稳定持久化，并补充对应后端回归测试。
- 修复账号导入弹窗中样例文本的换行展示，避免示例格式被挤成单行后影响批量导入判断。
- 修复桌面端设置页中“按天数”/“Cron 表达式”等选项卡在向下滚动时覆盖“系统设置”标题栏的问题，改为内容区独立滚动并同步调整侧栏联动逻辑。

## [2.0.23] - 2026-04-19

### Added
- 顶部导航新增版本信息展示，支持查看当前版本、复制版本号并跳转到更新日志。

### Changed
- 调整导航品牌区布局，将版本信息与 GitHub 入口整理为更统一的产品元信息区域。
- 重绘 GitHub Star 按钮样式，改为更贴合当前控制台风格的胶囊按钮，并补充 hover、active、focus 反馈。

### Fixed
- 修复顶部版本信息在部分浏览器环境下点击无响应的问题，改为更稳定的全局触发方式。

## [2.0.22] - 2026-04-17

### Fixed
- 修复动态覆盖后的 `PUT /api/accounts/<id>`、`GET /api/emails/<email>`、`GET /api/external/emails` 丢失鉴权装饰器的问题，避免未登录或未携带 API Key 时绕过访问控制。
- 为动态路由覆盖增加启动期保护断言，若关键 endpoint 被未包装函数替换会在应用启动时直接报错，防止鉴权再次静默失效。
- 补充外部邮件接口、内部邮件接口、账号更新接口和动态 endpoint 保护标记的回归测试，覆盖实际 401 行为与路由注册状态。

## [2.0.21] - 2026-04-17

### Added
- 为邮件详情增加附件列表展示与下载能力，支持 Graph 和 IMAP 邮箱直接查看并下载邮件附件。

### Fixed
- 修复 IMAP 纯文本邮件详情被错误拼接为带字面量 `<br>` 的正文内容问题，现按纯文本正确返回。

## [2.0.20] - 2026-04-16

### Added
- 左侧账号列表新增“复制邮箱+别名”批量操作，可一次复制所选账号的主邮箱和全部别名邮箱，并自动去重后写入剪贴板。

## [2.0.19] - 2026-04-15

### Added
- 新增内置 `2925邮箱` 类型，默认使用 `imap.2925.com:993`，并补充域名到 provider 的自动识别和前端导入/编辑下拉项。

### Fixed
- 修复部分自定义 IMAP / 2925 IMAP 服务端无法正确返回 `SEARCH` / `UID SEARCH` 结果时，收件箱明明有邮件却列表为空的问题。
- 为 IMAP 列表与详情查询增加 `UID SEARCH -> SEARCH -> 按 EXISTS 数量直接 FETCH` 的多层回退，兼容实现不标准的服务器。

## [2.0.18] - 2026-04-15

### Added
- 新增项目运行时后端模型，支持按 `project_key` 管理邮箱在项目内的独立状态，并提供启动项目、项目列表、项目账号列表、领取、成功、失败、释放、重置失败、移出项目、恢复项目等完整接口。
- 为项目运行时补充后端回归测试，覆盖启动项目、分组范围补全、失败后需人工重置、删除后重导入同邮箱沿用旧项目状态等关键路径。

### Changed
- 将“创建项目 + 范围补全”设计收敛为单一“启动项目”语义，重复启动同一项目时只补全新增邮箱，不重置已有项目状态。
- 项目内邮箱身份改为按邮箱地址而不是纯 `account_id` 维护，避免删除后重导入同邮箱绕过既有 `done` / `failed` 状态。

### Documentation
- 补充 `docs/api.md` 中的项目管理接口文档，覆盖状态说明、启动项目语义、查询参数、关键请求/响应示例，以及 `deleted` 与重导入复用规则。

## [2.0.17] - 2026-04-15

### Added
- 新增企业微信群机器人 Webhook 转发渠道，只需填写 Webhook 地址即可作为独立转发通道使用。
- 为企业微信转发补充设置持久化、测试发送和基础回归测试，覆盖设置保存与实际发送调用。

### Changed
- 修改发布流程，支持推送 `vX.Y.Z` 版本标签后自动触发 GitHub Release 工作流，手动触发改为兜底方案。
- 调整 Docker 构建参数，关闭 provenance / SBOM attestation，避免 GHCR 发布版本额外显示 `unknown/unknown` 平台条目。


## [2.0.16] - 2026-04-15

### Changed
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
- Fixed aggregated `folder=all` ordering for IMAP/Gmail mailboxes by normalizing RFC822 timestamps that include trailing timezone labels such as `(UTC)`.
- Fixed IMAP all-mail merging to prefer the server-reported `INTERNALDATE` when available so merged results are sorted by received time instead of unreliable header `Date`.
- Fixed the mobile mail list layout so very long sender addresses no longer push the card outside the viewport, and folder badges now wrap to a new line on narrow screens.

## [2.0.11] - 2026-04-14

### Fixed
- Fixed the manual GitHub release workflow packaging path so Windows release assets and Docker release publication no longer fail during the release run.

## [2.0.10] - 2026-04-13

### Changed
- Changed `folder=all` mailbox aggregation to fetch `inbox` and `junkemail` in parallel before merging and sorting the result list.

### Fixed
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
- Moved proxy failover configuration from system-wide settings into each mailbox group so different groups can use different fallback chains.

### Fixed
- Fixed Outlook token refresh and Graph requests failing immediately when the primary group proxy was unreachable by retrying through configured fallback proxies in order.
- Fixed the group settings dialog copy to document that `回退代理 1` and `回退代理 2` both support `direct` / `直连` as explicit direct-connect fallbacks.

## [2.0.7] - 2026-04-11

### Changed
- Replaced the custom Windows tray implementation with a `pystray`-based tray menu and generated application icon.

### Fixed
- Fixed the packaged Windows desktop app tray menu labels and icon rendering issues.
- Removed the brittle dependency on low-level Win32 `ctypes` tray bindings that caused repeated Windows-specific startup failures.

## [2.0.6] - 2026-04-11

### Fixed
- Fixed additional Windows tray startup crashes by replacing more `ctypes.wintypes` handle annotations with compatibility-safe Win32 handle definitions.

## [2.0.5] - 2026-04-11

### Fixed
- Fixed the Windows tray bootstrap using unavailable `ctypes.wintypes` symbols (`LRESULT`, `WNDPROC`) that caused the packaged app to crash during startup.

## [2.0.4] - 2026-04-11

### Added
- Added a Windows system tray controller for the packaged desktop app with `打开界面` and `退出` actions.

### Changed
- Switched the packaged Windows desktop runtime to a controllable background server so the tray can exit the app cleanly.

### Fixed
- Fixed the Windows packaged app having no visible way to quit after launching the browser UI.

## [2.0.3] - 2026-04-11

### Fixed
- Fixed Windows `exe` packaging to include Python modules imported from dynamically executed segmented files, preventing startup crashes such as `ModuleNotFoundError: No module named 'imaplib'`.
- Made the PyInstaller hidden-import list derive automatically from the segmented source files so future segment imports are included in packaged builds.

## [2.0.2] - 2026-04-11

### Changed
- Switched the packaged desktop build to GUI mode and auto-open the local web UI in the browser on startup.

### Fixed
- Fixed packaged startup diagnostics so desktop launch failures are written to `startup-error.log` and surfaced to Windows users with a dialog instead of silently exiting.
- Fixed the packaged desktop default bind host to use `127.0.0.1`, avoiding local browser access issues on some Windows machines.

## [2.0.1] - 2026-04-11

### Added
- Added automated Windows `exe` packaging in the tag-based GitHub Release workflow.
- Added a PyInstaller spec and packaged-runtime resource handling for the desktop build.

### Changed
- Documented the Windows desktop distribution flow in the README, deployment guide, and release guide.

### Fixed
- Fixed packaged execution so templates, static assets, database storage, and `SECRET_KEY` persistence work correctly after bundling.

## [2.0.0] - 2026-04-09

### Changed
- Formalized the repository into a release-managed project with `main` / `dev` branch roles, semantic versioning, and documented release flow.
- Added automated GitHub Release generation and clarified collaboration / branch-protection guidance for future contributors.
- Tightened Docker image publishing policy so documentation-only changes no longer trigger image builds.

### Added
- Added `VERSION`, `CHANGELOG.md`, `RELEASE.md`, and `BRANCH_PROTECTION.md` to make versioning, release, and collaboration rules explicit.
- Added release-tag driven image/version workflow for `latest`, `dev`, and semantic version tags.

### Fixed
- Fixed invalid Docker image tag generation caused by `docker/metadata-action` in tag-triggered builds.

## [1.0.0] - 2026-04-07

### Added
- Stable initial release baseline for the Outlook mail management tool.
- Web UI for mailbox group management, mailbox import, and mail browsing.
- Outlook access via Microsoft Graph API, new IMAP, and legacy IMAP fallback.
- Temporary mailbox integration for GPTMail, DuckMail, and Cloudflare Temp Email.
- External API access using API Key authentication.
- Docker and Docker Compose deployment support.
