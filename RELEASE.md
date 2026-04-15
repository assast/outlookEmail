# 发版说明

本文档用于说明本仓库的标准发版流程、版本号规则、GitHub Actions 行为，以及发版后的核对步骤。

## 适用范围

- 日常开发分支：`dev`
- 稳定发布分支：`main`
- 版本标签自动发布：`git push origin vX.Y.Z`
- 手动发布工作流：`Create GitHub Release`

## 版本号规则

项目采用语义化版本号：

- `MAJOR.MINOR.PATCH`
- 示例：`2.0.15`

约定：

- 推送形如 `v2.0.16` 的 Git 标签会自动触发发布工作流
- GitHub Actions 手动发版时，输入的是不带 `v` 的版本号，例如 `2.0.15`
- 工作流会自动创建对应标签 `v2.0.15`
- `CHANGELOG.md` 中的版本标题也必须写成 `## [2.0.15] - 2026-04-15`

## 发版产物

推送版本标签或手动触发 `Create GitHub Release` 工作流后，会自动生成以下产物：

- Git 标签：`vX.Y.Z`
- GitHub Release：标题为 `vX.Y.Z`
- Windows 桌面压缩包：`OutlookEmail-windows-x64-X.Y.Z.zip`
- Docker 镜像：`ghcr.io/assast/outlookemail:vX.Y.Z`

补充说明：

- `latest` / `main` / `dev` 标签来自分支推送触发的 Docker 工作流
- Release 工作流负责发布版本镜像 `vX.Y.Z`
- GitHub Release 正文优先从 `CHANGELOG.md` 中提取对应版本条目

## 发版前检查

建议在发版前逐项确认：

1. 目标提交已经合并到 `main`，且 `main` 处于可发布状态。
2. `VERSION` 已更新为本次版本号。
3. `CHANGELOG.md` 已新增本次版本条目，日期与内容完整。
4. `README.md`、部署文档、升级文档中涉及的行为说明没有与当前实现冲突。
5. 如本次改动影响 Docker、Windows `exe`、环境变量、API 或前端交互，已同步写入文档。
6. 本地或 CI 已完成必要验证，至少确认核心功能没有明显回归。

## 标准发版步骤

### 1. 在 `dev` 完成功能开发与验证

建议先在 `dev` 分支完成功能、修复和文档整理，再合并到 `main`。

### 2. 合并到 `main`

确保 `main` 上的提交就是准备发布的最终代码。

### 3. 更新版本号

同步更新以下内容：

- `VERSION`
- `CHANGELOG.md`

示例：

```txt
VERSION            -> 2.0.15
CHANGELOG.md 标题  -> ## [2.0.15] - 2026-04-15
```

### 4. 提交并推送 `main`

```bash
git checkout main
git pull
git add VERSION CHANGELOG.md README.md RELEASE.md docs/
git commit -m "docs: prepare release 2.0.15"
git push origin main
```

如果本次发版还包含代码变更，请把代码文件一并提交。

### 5. 推送版本标签触发自动发布

```bash
git tag -a v2.0.16 -m "Release v2.0.16"
git push origin v2.0.16
```

推送后，`Create GitHub Release` 工作流会自动运行并发布该版本。

### 6. 手动触发 GitHub Release 工作流（兜底）

如果你不想通过推送 tag 触发，或者需要补发某个版本，也可以进入 GitHub Actions 手动运行：

- 工作流名称：`Create GitHub Release`
- 输入参数：`version`
- 输入示例：`2.0.15`

不要填写 `v2.0.15`，否则会生成错误标签。

## 工作流实际执行内容

`Create GitHub Release` 工作流会依次执行以下阶段：

### 1. 构建 Windows `exe`

- 使用 `pyinstaller --noconfirm --clean outlookEmail.spec`
- 打包 `dist/OutlookEmail.exe`
- 与 `README.md` 一起压缩为发布附件

### 2. 创建并推送标签

- 手动触发时会自动创建 `vX.Y.Z`
- tag push 触发时会直接复用当前推送的 `vX.Y.Z`
- 如果同名标签已经存在且指向当前提交，会跳过创建
- 如果同名标签存在但指向别的提交，工作流会失败并停止发布

### 3. 生成 Release Notes

工作流会从 `CHANGELOG.md` 中提取当前版本对应的内容：

- 匹配格式：`## [X.Y.Z]`
- 如果没有匹配到，会退回到一个非常简短的默认说明

因此，正式发版前应确保 `CHANGELOG.md` 已提前写好该版本条目。

### 4. 构建并推送 Docker 版本镜像

工作流会调用 `docker-build-push.yml`，并基于标签 `refs/tags/vX.Y.Z` 构建：

- `ghcr.io/assast/outlookemail:vX.Y.Z`

### 5. 发布 GitHub Release

最终会创建正式 Release，并上传 Windows 压缩包附件。

## 发版后核对

建议至少检查以下项目：

1. GitHub Release 页面已生成，标题和正文正确。
2. Release 附件可下载，文件名包含本次版本号。
3. 仓库标签页中存在 `vX.Y.Z`。
4. GHCR 中可拉取版本镜像：

```bash
docker pull ghcr.io/assast/outlookemail:v2.0.15
```

5. 如本次版本包含部署或接口变更，抽样验证一台测试环境升级成功。

## 常见问题

### 为什么 GitHub Release 正文不完整？

通常是 `CHANGELOG.md` 中没有写对应版本标题，或标题格式不匹配。正确格式示例：

```md
## [2.0.15] - 2026-04-15
```

### 为什么工作流提示标签已存在但 SHA 不一致？

说明同名标签已经被打到其他提交上。此时不要继续强行发版，应该先确认：

- 本次是否用了重复版本号
- `main` 是否已经发生额外提交
- 历史标签是否曾被错误创建

### 为什么没有刷新 `latest` 镜像？

因为 Release 工作流只发布 `vX.Y.Z` 镜像。`latest` / `main` / `dev` 来自分支推送触发的 Docker 工作流，而不是 Release 工作流。

## 建议的发版节奏

1. 平时在 `dev` 累积开发与修复。
2. 准备发布时合并到 `main`。
3. 先补齐 `CHANGELOG.md` 和相关文档，再推送 `vX.Y.Z` 标签触发自动发版。
4. 发版后用 `vX.Y.Z` 镜像做一次实际部署验证。
