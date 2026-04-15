# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [Unreleased]
- 修改发布流程，支持推送 `vX.Y.Z` 版本标签后自动触发 GitHub Release 工作流，手动触发改为兜底方案。


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
