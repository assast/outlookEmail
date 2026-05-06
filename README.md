# 多邮箱邮件管理工具

一个面向多邮箱账号场景的邮件管理工具，支持通过 Outlook/Hotmail OAuth、Microsoft Graph API 和标准 IMAP 统一读取、管理和转发邮件，并提供 Web 界面用于分组管理、账号管理、邮件查看和对外 API 调用。当前支持 Outlook/Hotmail、Gmail、QQ、163、126、Yahoo、阿里邮箱以及自定义 IMAP 邮箱，同时集成 GPTMail、DuckMail、Cloudflare Temp Email 多提供商临时邮箱能力。
## 📦 快速开始
### 体验站点
https://aso.de5.net
admin123
注意：体验站点请勿修改密码或存放实际数据，部署在无持久化的服务上，数据随时可能丢失恢复初始状态

## 🌿 版本管理与发布

本项目采用轻量化双分支版本管理：

- `main`：稳定分支，只保留可发布版本
- `dev`：开发分支，日常功能开发与修复默认在这里进行

标准发版流程：

1. 在 `dev` 分支完成开发与验证
2. 合并到 `main`
3. 更新 `VERSION` 与 `CHANGELOG.md`
4. 推送 `main`
5. 手动触发 GitHub Actions 的 `Create GitHub Release` 工作流，并传入不带 `v` 的版本号，例如 `2.0.15`

手动发版工作流会自动：

- 构建 Windows `exe` 并打包为 Release 附件
- 创建并推送对应标签，例如 `v2.0.15`
- 根据 `CHANGELOG.md` 中对应版本条目生成 GitHub Release 正文
- 构建并发布正式版本镜像 `ghcr.io/assast/outlookemail:v2.0.15`

Docker 镜像标签约定：

- `ghcr.io/assast/outlookemail:latest`：默认分支最近一次符合条件的稳定构建
- `ghcr.io/assast/outlookemail:main`：`main` 分支最近一次符合条件的构建
- `ghcr.io/assast/outlookemail:dev`：`dev` 分支最近一次符合条件的构建
- `ghcr.io/assast/outlookemail:vX.Y.Z`：正式版本镜像

更完整的发版步骤、工作流行为和核对清单见 [发版说明](RELEASE.md)。

### 方式一：下载 Windows `exe`(win可用)

从 GitHub Releases 下载对应版本的 `OutlookEmail-windows-x64-*.zip`，解压后直接运行 `OutlookEmail.exe` 即可。

桌面版首次启动会自动：

- 生成并持久化 `SECRET_KEY`
- 创建本地数据目录和 SQLite 数据库
- 启动 Web 服务，默认地址 `http://127.0.0.1:5000`

说明：

- Windows 数据默认保存在 `%APPDATA%\OutlookEmail`
- 默认登录密码仍然是 `admin123`，首次登录后建议立即修改

### 方式二：使用 Docker（推荐服务器部署）

```bash
# 拉取最新镜像
docker pull ghcr.io/assast/outlookemail:latest

# 运行容器
docker run -d \
  --name outlook-mail-reader \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e LOGIN_PASSWORD=admin123 \
  -e SECRET_KEY=your-secret-key-here \
  ghcr.io/assast/outlookemail:latest
```

### 方式三：使用 Python 直接运行

```bash
git clone https://github.com/assast/outlookEmail.git
cd outlookEmail
pip install -r requirements.txt
export SECRET_KEY=your-secret-key-here
python web_outlook_app.py
```

访问 `http://localhost:5000` 即可使用。
如果是服务器部署，仍然建议显式设置固定 `SECRET_KEY`。

### 使用 Docker Compose

```yaml
version: '3.8'
services:
  outlook-mail-reader:
    image: ghcr.io/assast/outlookemail:latest
    container_name: outlook-mail-reader
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - LOGIN_PASSWORD=admin123
      - SECRET_KEY=your-secret-key-here
      - FLASK_ENV=production
    restart: unless-stopped
```

```bash
docker-compose up -d
```

#### 可选：启用界面 Docker 在线更新

界面里的 Docker 在线更新需要访问宿主机 Docker socket。`/var/run/docker.sock` 具有宿主机 Docker 管理权限，只建议在可信环境开启。

该功能只适用于使用可变镜像标签的容器，例如 `latest`、`main`、`dev`。如果当前容器固定使用 `v2.0.39` 这类版本标签，界面会拒绝在线更新，因为 Watchtower 不会自动把固定标签切换到新版本标签。
可选环境变量 `DOCKER_UPDATE_STATUS_TIMEOUT` 用于单独控制状态查询和容器 inspect 的超时时间（秒），不影响实际更新任务的 `DOCKER_UPDATE_TIMEOUT`。

```yaml
version: '3.8'
services:
  outlook-mail-reader:
    image: ghcr.io/assast/outlookemail:latest
    container_name: outlook-mail-reader
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - LOGIN_PASSWORD=admin123
      - SECRET_KEY=your-secret-key-here
      - FLASK_ENV=production
      - DOCKER_UPDATE_ENABLED=true
      - DOCKER_UPDATE_CONTAINER=outlook-mail-reader
    restart: unless-stopped
```

## ✨ 功能特性

### 邮件读取方式

本工具当前包含三类读取链路：

1. **Outlook/Hotmail OAuth + Graph API** - 优先方式，适合 Outlook / Hotmail / Live 账号
2. **Outlook/Hotmail OAuth + IMAP 回退** - `outlook.live.com` / `outlook.office365.com`
3. **标准 IMAP** - 适用于 Gmail、QQ、163、126、Yahoo、阿里邮箱和自定义 IMAP

### Web 应用功能

#### 核心功能
- 🔐 **登录验证** - 密码保护的 Web 界面，支持在线修改密码
- 📁 **分组管理** - 支持创建、编辑、删除邮箱分组，自定义分组颜色，支持分组级别代理设置
- 🌐 **分组代理** - 每个分组可配置 HTTP/SOCKS5 代理
- 📧 **多邮箱管理** - 批量导入和管理 Outlook/Hotmail OAuth / IMAP 邮箱账号
- 🪪 **别名管理** - 支持给单个邮箱配置多个别名邮箱，主邮箱和别名都可用于检索邮件和调用对外 API
- 🔀 **别名高级用法** - 可将外部邮箱自动转发到本项目管理的邮箱 A，再把外部邮箱配置为 A 的别名，从而通过本项目统一读取邮件
- 📬 **邮件查看** - Web 界面支持查看收件箱和垃圾邮件；API 支持 `inbox`、`junkemail`、`deleteditems`、`all`
- 📎 **附件下载** - 邮件详情支持单个附件下载，也支持将全部附件打包为 ZIP 下载
- 🔍 **全屏查看** - 支持全屏模式查看邮件
- 📤 **导出功能** - 支持按分组或全部导出邮箱账号信息
- 🧩 **WebDAV 备份** - 支持将“导出全部分组”的文件按 Cron 定时上传到 WebDAV，也可手动上传
- 🎨 **现代化 UI** - 四栏布局，账号列表、邮件列表、邮件详情分区清晰
- ⚡ **性能优化** - 邮件列表与账号列表缓存，分组切换和账号切换更快
- 📄 **分页加载** - 滚动到底部自动加载下一页（每页20封）
- 🔥 **临时邮箱** - 集成 GPTMail + DuckMail + Cloudflare Temp Email，多提供商生成、导入、读取和查看详情
- ⚙️ **系统设置** - 在线修改密码、API Key 等
- 🔄 **OAuth2 助手** - 内置授权流程，快速获取 Refresh Token
- 💾 **邮件缓存** - 智能缓存邮件列表，切换即时展示
- 🏷️ **标签管理** - 支持给邮箱打标签、批量操作、按标签筛选
- 📦 **批量移动分组** - 批量选择邮箱移动到指定分组
- ✅ **批量选择** - 邮箱列表、邮件列表均支持全选当前列表与清空选择
- 🗑️ **邮件删除** - 单封/批量永久删除邮件
- 🔄 **API 优先级回退** - Graph API → IMAP(新) → IMAP(旧) 自动回退
- 🔑 **对外 API** - 通过 API Key 直接获取邮件，无需登录，支持别名邮箱、聚合文件夹和多条件筛选 带+号的附加电子邮箱自动识别，自动回退主邮箱/别名邮箱查询

#### 邮件转发
- 📮 **按账号开启转发** - 每个账号单独控制是否参与自动转发
- 📨 **多渠道转发** - 支持 SMTP 邮件转发和 Telegram 转发
- ⏱️ **时间窗口控制** - 支持仅转发最近 X 分钟内收到的邮件
- 🗑️ **垃圾箱转发可选** - 可配置是否把垃圾邮件一起纳入转发
- 📚 **转发历史** - 支持查看最近转发记录和失败记录
- ▶️ **手动触发** - 支持从界面手动触发一次转发检查

#### Token 刷新管理
- 🔁 **全量刷新** - 一键刷新所有 Outlook/Hotmail OAuth 账号 Token
- ⏰ **定时刷新** - 支持按天数或 Cron 表达式配置，Docker / Docker Compose 启动也会自动生效
- 📊 **刷新统计** - 实时显示失败邮箱数量
- 📜 **刷新历史** - 近半年完整记录

#### WebDAV 备份
- 🗂️ **全部分组备份** - 备份文件复用“导出全部分组”的格式，包含普通邮箱和临时邮箱分组数据
- ⏲️ **Cron 定时上传** - 支持 5 段 Cron 表达式，并使用常规设置里的应用时区计算下次执行时间
- 🧪 **连接测试** - 可在设置页上传并清理测试文件，用于验证 WebDAV 目录是否可写
- 🔐 **敏感操作确认** - 修改备份设置和手动上传真实备份时需要再次验证登录密码

#### 安全特性
- 🛡️ XSS 防护 | 🔒 CSRF 防护 | 🔐 数据加密 | 🚦 速率限制 | 📋 审计日志 | 🔑 二次验证

### 界面布局

Web 应用采用四栏式布局设计：
1. **分组面板** - 显示所有邮箱分组，点击切换
2. **邮箱面板** - 显示当前分组下的邮箱账号列表
3. **邮件列表** - 显示选中邮箱的邮件，支持切换文件夹和滚动加载
4. **邮件详情** - 显示选中邮件的完整内容（支持 HTML 渲染）

## 📸 界面预览

### 邮箱列表界面
![邮箱列表](img/邮箱列表.png)

### 全局搜索功能
![全局搜索](img/全局搜索.png)

### 导入邮箱账号
![导入邮箱账号](img/导入邮箱账号.png)

### Token 刷新管理
![全量刷新Token](img/全量刷新token.png)

### 标签管理功能
![标签管理](img/标签管理.png)

## 📖 使用说明

### 1. 获取 OAuth2 凭证（这一步非必须，买的账号如果是带令牌的可以跳过这一步; 项目本身也内置了默认的客户端id，如果忽略这一步则使用的是默认客户端id，就可以直接从本节的步骤5开始）

要使用本工具，您需要获取以下 OAuth2 凭证：

1. **Client ID** - Microsoft Azure 应用注册的客户端 ID
2. **Refresh Token** - OAuth2 刷新令牌

#### 步骤 1：注册 Azure 应用（这一步看目前的情况得E3 或者 E5 或者其他的开发者账号才能创建）

访问 [Azure Portal](https://portal.azure.com/)，进入「应用注册」：

![应用注册](img/应用注册.png)

#### 步骤 2：创建新应用

点击「新注册」，填写应用信息：

![注册应用程序](img/注册应用程序.png)

- **名称**：自定义应用名称
- **支持的账户类型**：选择「任何组织目录中的账户和个人 Microsoft 账户」
- **重定向 URI**：选择「公共客户端/本机」，填写 `http://localhost:8080`

#### 步骤 3：获取应用程序 ID

创建完成后，复制「应用程序(客户端) ID」：

![获取应用程序ID](img/获取应用程序ID.png)

#### 步骤 4：配置 API 权限  这一步应该可以省略，目前内置的客户端id就没有设置这一步也能正常使用

在「API 权限」中添加以下权限：
- `offline_access` - 获取刷新令牌
- `Mail.Read` - 读取邮件
- `Mail.ReadWrite` - 读写邮件
- `User.Read` - 读取用户信息
- `IMAP.AccessAsUser.All` - IMAP 访问

#### 步骤 5：获取 Refresh Token

使用本工具内置的 OAuth2 助手获取 Refresh Token：

![换取token](img/换取token.png)

1. 在 Web 界面点击「获取 Token」按钮
2. 点击「生成授权链接」
3. 复制链接到浏览器打开，完成授权
4. 复制授权后的完整 URL（处于安全考虑，我没有统一建设授权回调服务，所有授权都在自己部署的服务内完成，不会外泄，所以重定向URI为http://localhost:8080，这个链接肯定是打不开的，所以要复制过来在部署的服务走后半段的换取Refresh Token）
5. 粘贴到「授权后的 URL」输入框
6. 点击「换取 Token」按钮
7. 复制获得的 Refresh Token

### 2. 导入邮箱账号

在 Web 界面中点击「导入邮箱」后，可根据邮箱类型选择对应导入格式。

#### Outlook/Hotmail OAuth

支持两种格式：

```txt
邮箱----密码----client_id----refresh_token
邮箱----密码----refresh_token----client_id
```

示例：

```txt
user@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA...
```

#### 标准 IMAP 邮箱

适用于 Gmail、QQ、163、126、Yahoo、阿里邮箱等：

```txt
邮箱----IMAP授权码/应用密码
```

示例：

```txt
user@gmail.com----app-password
user@qq.com----imap-auth-code
```

#### 自定义 IMAP

支持两种格式：

```txt
邮箱----IMAP密码
邮箱----IMAP密码----imap_host----imap_port
```

示例：

```txt
user@example.com----app-password
user@example.com----app-password----imap.example.com----993
```

支持批量导入，每行一个账号。导入时可选择是否立即开启邮件转发。普通邮箱导入时不能选择临时邮箱分组。

### 3. 查看邮件

1. 从左侧选择分组
2. 选择邮箱账号
3. 点击「获取邮件」按钮
4. 在 Web 界面切换「收件箱」「垃圾邮件」查看邮件
5. 滚动到邮件列表底部自动加载下一页（每页 20 封）
6. 点击邮件查看详情，支持 HTML 渲染与全屏查看
7. 需要查看 `deleteditems` 或 `all` 聚合结果时，建议使用对外 API 或内部 API

### 4. 别名管理

1. 打开某个邮箱账号的「编辑账号」
2. 在「别名邮箱」中按行填写多个别名
3. 保存后，主邮箱和别名都会指向同一个账号

适合这些场景：

- 同一账号有多个注册邮箱名称
- 某些站点使用了 `user+tag@example.com`
- 外部邮箱自动转发到本项目管理邮箱后，希望继续用原邮箱名来取信

### 5. 邮件转发

邮件转发分成两层控制：

1. **账号级开关**
   在导入账号或编辑账号时，选择是否为该账号开启转发
2. **全局转发设置**
   在「设置 -> 邮件转发设置」中配置：
   - 轮询间隔
   - 转发邮件时间范围
   - 是否转发垃圾箱邮件
   - 转发渠道（SMTP / Telegram）
   - SMTP / Telegram 的具体参数

补充说明：

- 转发轮询只处理“账号里已开启转发”的邮箱
- 可以手动触发一次转发检查
- 可以查看最近转发历史和失败记录

### 6. WebDAV 备份

在「设置 -> WebDAV 备份」中配置：

1. 填写 WebDAV 目录 URL，例如 `https://dav.example.com/backups`
2. 按需填写 WebDAV 用户名和密码 / App Password
3. 填写 5 段 Cron 表达式，例如 `0 3 * * *`
4. 点击「计算下次执行时间」确认 Cron 预览，时间会使用常规设置里的应用时区
5. 点击「测试 WebDAV」验证目录可写；测试只上传临时测试文件，不需要登录密码
6. 修改备份设置时，在“敏感操作确认”中输入登录密码后保存

补充说明：

- 定时备份会上传与“导出全部分组”一致的文本文件，文件名形如 `all_groups_backup_YYYYMMDD_HHMMSS.txt`
- 「手动上传」会立即上传真实备份文件，需要输入登录密码
- WebDAV 备份涉及账号、令牌、临时邮箱凭据等敏感数据，建议使用专用 WebDAV 目录并控制访问权限

### 7. 对外 API

通过 API Key 直接获取邮件，无需登录 Web 界面。

当前额外支持：

- 使用主邮箱或别名邮箱取信
- `folder=all` 一次聚合收件箱和垃圾邮件并按标准化后的邮件时间倒序排序，`top` 按每个文件夹分别计算
- 支持按主题、发件人、关键词筛选列表
- 支持特殊字符别名，例如 `user+alias@example.com`
- 默认 `top=1`

**配置步骤：**
1. 点击「⚙️ 设置」→ 在「对外 API Key」处点击「🔑 随机生成」→ 保存

**调用示例：**
```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=alias@example.com&folder=all&top=10"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=alias@example.com&folder=all&top=10&subject_contains=verify&from_contains=github&keyword=reset"

curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user%2Balias%40example.com"
```

如果邮箱或别名里带特殊字符：

- `@` 可以直接传
- `+` 建议编码成 `%2B`
- `&` 必须编码成 `%26`

如果你把外部邮箱 B 自动转发到本项目管理的邮箱 A，再把 B 配成 A 的别名，那么后续可以直接用 B 作为 `email` 参数调用对外 API。

详细文档见 [API 文档](docs/api.md)。

## 📚 详细文档

| 文档 | 说明 |
|------|------|
| [🚀 部署指南](docs/deployment.md) | Docker、Docker Compose、Nginx/Caddy 部署、环境变量配置 |
| [⬆️ 升级指南](docs/upgrade.md) | Windows、Docker、Python 直跑升级与回滚建议 |
| [🔐 安全配置](docs/security.md) | XSS/CSRF 防护、数据加密、速率限制、审计日志 |
| [📡 API 文档](docs/api.md) | 对外 API、内部 API 端点、代理配置 |
| [🛠️ 故障排查](docs/troubleshooting.md) | 常见问题、故障排查步骤 |
| [📋 更新日志](CHANGELOG.md) | 版本更新历史 |
| [🚢 发版说明](RELEASE.md) | 标准发版步骤、版本号规则、GitHub Release 说明 |
| [🛡️ 分支保护建议](BRANCH_PROTECTION.md) | main/dev 使用边界、保护规则与构建触发建议 |

## 🏗️ 技术架构

### 后端技术栈
- **Flask 3.0+** - Web 框架
- **SQLite 3** - 数据库
- **Requests / requests[socks]** - HTTP 客户端与代理支持
- **IMAP4_SSL** - IMAP 协议支持
- **Microsoft Graph API** - Outlook/Hotmail 邮件 API
- **APScheduler + croniter** - 定时刷新与转发轮询
- **bcrypt + cryptography** - 密码哈希与敏感字段加密

### 前端技术栈
- **原生 JavaScript** - 无框架依赖
- **CSS3** - 现代化样式
- **Fetch API** - 异步请求
- **DOMPurify 3.0.8** - HTML 净化

### 系统要求
- Python 3.9+
- SQLite 3
- Docker（可选）
- 2GB+ 内存

## 📝 依赖说明

```txt
flask>=3.0.0
flask-wtf>=1.2.0          # CSRF 防护（推荐安装）
werkzeug>=3.0.0
requests[socks]>=2.25.0   # HTTP 请求与代理支持
APScheduler>=3.10.0       # 定时任务
croniter>=1.3.0           # Cron 表达式解析
bcrypt>=4.0.0             # 密码哈希
cryptography>=41.0.0      # 数据加密
```
## 常见问题
### Gmail怎么获取应用密码
开启2fa，然后在这里创建应用密码

https://support.google.com/mail/answer/185833?hl=zh-Hans


### 怎么获取tg的群组id 和 用户id
#### 获取个人 ID (User ID)
在 Telegram 搜索框搜索 @userinfobot 或 @getmyid_bot。

点击 Start。

机器人会立即回复你的 User ID（一串数字）。

如果你想知道别人的 ID：只需将对方发给你的消息转发给这个机器人，它就会显示该用户的 ID。


#### 获取群组 ID (Group ID)
将上述机器人（如 @getmyid_bot）拉进你的群组。

在群组里输入 /myid（或者机器人指定的指令）。

机器人会返回该群组的 ID。

注意： 普通群组 ID 通常以数字开头，而**超级群组（Supergroup）或频道（Channel）**的 ID 通常以 -100 开头。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

```bash
git clone https://github.com/assast/outlookEmail.git
cd outlookEmail
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python web_outlook_app.py
```

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 🙏 致谢
本项目已在 [LINUX DO 社区](https://linux.do/) 发布，感谢社区的支持与反馈。

- [Microsoft Graph API](https://docs.microsoft.com/graph/)
- [GPTMail](https://mail.chatgpt.org.uk)
- [Flask](https://flask.palletsprojects.com/)

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=assast/outlookEmail&type=Date)](https://star-history.com/#assast/outlookEmail&Date)

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！你的 Star 是我持续更新的动力！** ⭐

初次维护一个项目，2026年04月11日15:45:33才发现有几个pull没合并，非常抱歉，这是我的联系方式如果我没看到的话，可以提醒我一下，有好的建议也可以提，感谢~
邮箱：u3794336@outlook.com

## 免责声明
本项目仅供学习、研究和技术交流使用，请遵守相关平台和服务条款，不要用于违规、滥用或非法用途。
因使用本项目产生的任何风险和后果，由使用者自行承担。
