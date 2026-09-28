# 升级指南

本文档面向已经在使用本项目的用户，说明新版本发布后的升级步骤、备份建议和回滚思路。

## 升级前建议

升级前建议先完成以下操作：

1. 备份 `data/` 目录，至少保留数据库文件。
2. 记录当前使用的镜像标签、部署方式和关键环境变量。
3. 确认当前 `SECRET_KEY` 会继续保留，不要在升级时更换。
4. 如使用反向代理或自动化脚本，确认升级后端口、域名、路径没有变化。

## 必须保留的关键数据

升级时最重要的是保留以下内容：

- SQLite 数据库：`data/outlook_accounts.db`
- 固定 `SECRET_KEY`
- 自定义环境变量

如果 `SECRET_KEY` 被改掉，已保存的 Refresh Token、API Key、邮箱密码等敏感数据将无法解密。

## Docker 升级

### 升级到最新稳定分支构建

```bash
docker pull ghcr.io/assast/outlookemail:latest
docker compose down
docker compose up -d
```

### 升级到指定正式版本

建议正式环境优先使用明确版本号：

```bash
docker pull ghcr.io/assast/outlookemail:v2.0.15
docker compose down
docker compose up -d
```

如果使用 `docker-compose.yml`，也可以直接把镜像改为指定版本：

```yaml
services:
  outlook-mail-reader:
    image: ghcr.io/assast/outlookemail:v2.0.15
```

完成后执行：

```bash
docker compose up -d
```

## Windows `exe` 升级

### 在线升级

1. 登录应用并打开页面顶部的版本信息。
2. 发现新版本后点击「立即升级」，确认开始。
3. 等待下载、解压和重启完成；下载阶段会显示百分比、大小和速度，并允许取消。
4. 当前页面会在服务恢复后自动刷新并显示新版本。

在线升级继续使用 GitHub Release 中现有的 `OutlookEmail-windows-x64-X.Y.Z.zip`，不会下载额外安装器。升级文件临时保存在当前 EXE 所在目录，因此该目录必须允许当前用户创建、重命名和删除文件；程序不会申请 UAC 提权。

如果仓库版本已经更新、但对应 Release ZIP 尚未发布，页面会提示稍后重试，当前程序不会退出。

### 手动升级

无法使用在线升级时仍可沿用原方式：

1. 从 GitHub Releases 下载新版本 `OutlookEmail-windows-x64-*.zip`。
2. 退出旧程序。
3. 解压到新的目录或覆盖旧目录中的程序文件。
4. 保留原有数据目录 `%APPDATA%\\OutlookEmail`。
5. 启动新的 `OutlookEmail.exe`。

说明：

- 数据默认不在程序目录里，而是在 `%APPDATA%\\OutlookEmail`
- 不要随意删除该目录中的数据库或密钥文件
- 在线升级会先把旧程序备份为同目录的 `*.old.exe`，确认新版本成功监听 Web 端口后才删除
- 新版本无法启动时会自动恢复旧版本；如果替换期间断电或进程被系统强制终止，可退出相关进程后把 `*.old.exe` 手动改回原 EXE 文件名

## Python 直跑升级

```bash
git pull origin main
pip install -r requirements.txt
python web_outlook_app.py
```

如果你使用虚拟环境，请先激活对应环境再执行。

## 升级后检查

建议升级后至少确认以下内容：

1. 能正常打开登录页。
2. 原有账号、分组、标签、设置仍然存在。
3. 原有扁平分组仍显示为一级分组；新建子分组、选中父分组查看子分组账号均正常。
4. 至少抽查一个 Outlook 账号和一个 IMAP 账号可正常取信。
5. 如启用了对外 API，抽查一次 `/api/external/emails`。
6. 如启用了自动转发或定时刷新，检查任务是否仍正常运行。

## 推荐升级策略

### 生产环境

- 优先使用 `vX.Y.Z` 明确版本标签
- 先在测试环境验证，再升级正式环境
- 升级前先备份数据库

### 测试或个人环境

- 可以直接使用 `latest`
- 如果追踪开发版本，可使用 `dev`

## 回滚思路

如果升级后发现问题，可以按原部署方式回滚：

### Docker 回滚

```bash
docker pull ghcr.io/assast/outlookemail:v2.0.13
docker compose down
docker compose up -d
```

### Windows 回滚

- 换回旧版本 `exe`
- 保留原数据目录不变

### Python 回滚

```bash
git checkout <旧版本对应提交或标签>
pip install -r requirements.txt
python web_outlook_app.py
```

如果升级过程中数据库结构发生变化，回滚前应先确认旧版本是否兼容当前数据库。

## 常见问题

### 升级后登录失效或敏感数据异常

优先检查是否改动了 `SECRET_KEY`。这是最常见原因。

### 升级后 `latest` 和 Release 版本不一致

这是正常的：

- `latest` 通常对应默认分支最近一次符合条件的构建
- `vX.Y.Z` 对应正式发版时生成的版本镜像

正式环境建议固定到明确版本号。
