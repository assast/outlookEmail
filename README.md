# 多邮箱邮件管理工具

一个面向多邮箱账号场景的邮件管理工具，支持通过 Outlook/Hotmail OAuth、Microsoft Graph API 和标准 IMAP 统一读取、管理和转发邮件，并提供 Web 界面、Chrome/Edge 浏览器扩展，用于分组管理、账号管理、邮件查看和对外 API 调用。当前支持 Outlook/Hotmail、Gmail、QQ、163、126、Yahoo、阿里邮箱以及自定义 IMAP 邮箱，同时集成 GPTMail、DuckMail、Cloudflare Temp Email 多提供商临时邮箱能力。

注意：改密码会导致auth失效，需要重新授权
## 📦 快速开始
### 体验站点（可能非最新版本）
https://aso.de5.net
admin123
注意：体验站点请勿修改密码或存放实际数据，部署在无持久化的服务上，数据随时可能丢失恢复初始状态；并且由于大家都能登录看到，并且好像有进程在扫描，所以非常可能存在账号被盗的风险

## 🌿 版本管理与发布

本项目采用轻量化双分支版本管理：`main` 为稳定发布分支，`dev` 为日常开发分支。

完整的发版步骤、工作流行为和核对清单见 [发版说明](RELEASE.md)。

### 方式一：下载 Windows `exe`(win可用)

从 GitHub Releases 下载对应版本的 `OutlookEmail-windows-x64-*.zip`，解压后直接运行 `OutlookEmail.exe` 即可。

Windows 桌面版发现新版本后，可在页面顶部的版本入口点击「立即升级」。确认后应用会把现有 Release ZIP 下载到当前 EXE 所在目录，显示下载百分比和速度，完成后自动替换并重启；下载阶段可以取消。

桌面版首次启动会自动：

- 生成并持久化 `SECRET_KEY`
- 创建本地数据目录和 SQLite 数据库
- 启动 Web 服务，默认地址 `http://127.0.0.1:5000`

说明：

- Windows 数据默认保存在 `%APPDATA%\OutlookEmail`
- 在线升级要求当前 EXE 所在目录可写，不会申请管理员权限；如果目录不可写，请先把程序移动到普通可写目录
- 新版本启动失败时会自动恢复旧版本；如果升级期间断电，可将同目录的 `*.old.exe` 手动改回原文件名恢复
- 默认登录密码仍然是 `admin123`，首次登录后建议立即修改

### 方式二：下载 macOS 安装包

从 GitHub Releases 下载对应架构的 `OutlookEmail-macos-*-*.dmg`，打开后把 `OutlookEmail.app` 拖到 `Applications` 即可。

桌面版首次启动会自动：

- 生成并持久化 `SECRET_KEY`
- 创建本地数据目录和 SQLite 数据库
- 启动 Web 服务，默认地址 `http://127.0.0.1:5000`

说明：

- macOS 数据默认保存在 `~/Library/Application Support/OutlookEmail`
- 如果 macOS 提示Apple无法验证“OutlookEmail”是否包含可能危害Mac安全或泄漏隐私的恶意软件。可执行下面命令然后重试
  `sudo xattr -rd com.apple.quarantine /Applications/OutlookEmail.app` 
- 默认登录密码仍然是 `admin123`，首次登录后建议立即修改

### 方式三：使用 Docker（推荐服务器部署）

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

### 方式四：使用 Python 直接运行

```bash
git clone https://github.com/assast/outlookEmail.git
cd outlookEmail
pip install -r requirements.txt
export SECRET_KEY=your-secret-key-here
python web_outlook_app.py
```

python -m pip install -r requirements.txt; $env:SECRET_KEY = (& python -c "import secrets; print(secrets.token_hex(32))")[0]; $env:HOST="127.0.0.1"; python web_outlook_app.py

访问 `http://localhost:5000` 即可使用。
如果是服务器部署，仍然建议显式设置固定 `SECRET_KEY`。

### 运行模式

服务需要保持单 worker 运行。官方 Docker 镜像已固定为 Gunicorn 单 worker + 多线程；如果自定义部署，请不要增加 worker 数，需要并发时优先调整线程数。Token 刷新管理的流式任务会使用进程内短期状态，多个 worker 会导致任务初始化和 SSE 订阅落到不同进程。

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

#### 可选：启用界面 Docker 在线更新 + 使用自己的 Client ID 和回调 URL

界面里的 Docker 在线更新需要访问宿主机 Docker socket。`/var/run/docker.sock` 具有宿主机 Docker 管理权限，只建议在可信环境开启。

该功能只适用于使用可变镜像标签的容器，例如 `latest`、`main`、`dev`。如果当前容器固定使用 `v2.0.39` 这类版本标签，界面会拒绝在线更新，因为 Watchtower 不会自动把固定标签切换到新版本标签。
应用默认会在 daemon 明确返回“最低支持 API 版本”时自动按该版本重试；如果你的 Docker 环境或 socket 代理有特殊兼容要求，也可以显式设置 `DOCKER_UPDATE_API_VERSION`，其值可参考 `docker version --format '{{.Server.APIVersion}}'` 的输出。
可选环境变量 `DOCKER_UPDATE_STATUS_TIMEOUT` 用于单独控制状态查询和容器 inspect 的超时时间（秒），不影响实际更新任务的 `DOCKER_UPDATE_TIMEOUT`。
如果当前 `latest` / `main` / `dev` 标签没有新的镜像可拉取，界面会显示本次没有应用更新，而不是误报为更新失败。

如果想让界面里的「获取 Token」使用自己的 Azure 应用，请同时设置 `OAUTH_CLIENT_ID` 和 `OAUTH_REDIRECT_URI`。这两个值会用于生成 Microsoft 授权链接和换取 Refresh Token；换取成功后界面返回的 Client ID 需要和 Refresh Token 一起导入账号。未设置时会使用项目内置的默认 Client ID 和默认回调地址 `http://localhost:8080`。

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
      # 可选：在较新的 Docker daemon / socket 代理环境中显式指定 API 版本
      # - DOCKER_UPDATE_API_VERSION=1.52
      # 可选：让界面 OAuth 助手使用你自己的 Azure 应用
      # - OAUTH_CLIENT_ID=your-azure-application-client-id
      # - OAUTH_REDIRECT_URI=http://localhost:8080
    restart: unless-stopped
```

### 方式五：本地源码构建并运行（docker-compose.build.yml）

适合在本机基于源码自行构建镜像（而非拉取 `ghcr.io` 上的预构建镜像）后运行，便于本地改动后立即验证。

仓库根目录已提供 `docker-compose.build.yml`，它会用根目录的 `Dockerfile` 从源码构建镜像并启动容器。

#### 步骤 1：准备环境变量文件 `.env.local`

`docker-compose.build.yml` 通过 `env_file: .env.local` 注入环境变量，该文件**不存在时 Compose 会直接报错拒绝启动**，需先从模板复制并修改：

```bash
cp .env.example .env.local
```

至少修改以下两项：

```bash
# 生成随机串后填入 .env.local 的 SECRET_KEY
python -c 'import secrets; print(secrets.token_hex(32))'
```

- `SECRET_KEY`：填入上面生成的随机串（务必修改，勿用占位值；首尾空白会被忽略）
- `LOGIN_PASSWORD`：首次初始化时的登录密码，默认 `admin123`，建议改为强密码；**已写入数据库后**再改此变量不会覆盖当前密码。忘记密码请用 `scripts/reset_login_password.py`（见 [故障排除](docs/troubleshooting.md) / [安全配置](docs/security.md)）

可选：如需调整 Gunicorn 线程数 / 超时，在 `.env.local` 中追加 `GUNICORN_THREADS`、`GUNICORN_TIMEOUT`（不填则使用默认值 4 / 300）。

可选：普通 Outlook/IMAP 邮箱读取邮件列表的整体超时默认为 120 秒，可在「系统设置 -> 常规设置 -> 邮件获取超时」中调整（30-300 秒）；也可在首次启动前通过 `.env.local` 的 `MAIL_FETCH_OVERALL_TIMEOUT` 设置初始值。该值应小于 `GUNICORN_TIMEOUT`（默认 300 秒）。

#### 步骤 2：构建并启动

```bash
docker compose -f docker-compose.build.yml up -d --build
```

- `--build` 强制从源码重新构建镜像（镜像标签为 `outlookemail:local`）
- 容器名为 `outlook-mail`，映射端口 `5000:5000`
- 数据持久化在宿主机 `./data`；`./static`、`./templates` 以只读方式挂载，便于本地编辑模板/静态资源实时生效

启动后访问 `http://localhost:5000`，使用 `.env.local` 中的 `LOGIN_PASSWORD` 登录。

#### 步骤 3：常用运维命令

```bash
# 查看日志
docker compose -f docker-compose.build.yml logs -f

# 查看健康检查与状态
docker compose -f docker-compose.build.yml ps

# 改动源码后重新构建并重启
docker compose -f docker-compose.build.yml up -d --build

# 停止并移除容器（数据仍保留在 ./data）
docker compose -f docker-compose.build.yml down
```

> 提示：`docker-compose.build.yml` 默认未挂载宿主机 Docker socket，因此界面里的「Docker 在线更新」不可用——本地构建场景请直接用上面的 `up -d --build` 重新构建来更新。

## ✨ 功能特性

### 邮件读取方式

本工具当前包含三类读取链路：

1. **Outlook/Hotmail OAuth + Graph API** - 优先方式，适合 Outlook / Hotmail / Live 账号
2. **Outlook/Hotmail OAuth + IMAP 回退** - `outlook.live.com` / `outlook.office365.com`
3. **标准 IMAP** - 适用于 Gmail、QQ、163、126、Yahoo、阿里邮箱和自定义 IMAP

#### 普通邮箱本地保留行为与限制

普通邮箱本地保留开关 `normal_mail_local_retention_enabled` 默认关闭。用户需要在系统设置中明确开启后，普通 Outlook/Hotmail 与标准 IMAP 邮箱才会把列表元数据和已查看、补齐过的部分正文保存到本机 SQLite。

开启后，普通邮箱列表会优先从本地保留数据加载，命中时可立即显示最近一次保留的邮件列表；在本地优先模式下继续向下滚动加载更多，也会沿用本地保留分页，因此远程不可用时仍可查看超过首屏的已保留邮件。页面同时会在后台继续向 Graph API 或 IMAP 发起远程同步。远程同步成功后会把新列表元数据写回本地保留库；同步失败时，当前页面会保留本地列表并显示后台同步失败提示，而不会把列表清空。

后台同步发现本地尚未显示的新邮件时，页面会显示“有 N 封新邮件已同步”的非打断式提示。同步成功不会立即把新邮件并入当前列表；用户点击提示后，新邮件才会合并到当前列表，并执行高亮、列表缓存更新和新邮件正文保留的后台补齐，避免正在阅读或已选择的邮件被突然替换。

邮件详情会优先使用已保留的正文内容；如果本地行还没有正文，远程详情读取成功后会回填正文保留数据，供后续刷新页面、重启应用或临时网络失败时继续查看。若远程详情失败但本地已有正文，详情页会展示本地保留正文作为回退。关键词过滤也会先检查已缓存正文，只有缓存缺失时才补走远程详情读取。

Outlook/Hotmail OAuth 的 IMAP 回退链路默认按 UID 读取详情和附件；列表项、详情请求和附件下载可携带 `id_mode=uid|sequence`，避免 UID 与序列号混用导致取错邮件。标准 IMAP 账号继续使用其既有消息 ID 读取逻辑。

当前阶段只保留普通邮箱列表元数据和已读取过的详情正文，不包含附件二进制、原始 MIME 内容的下载或保留；附件下载仍依赖当前远程提供商链路。设置页会显示已保存邮件数、已缓存正文数、估算保留大小和当前 SQLite 数据库大小，并提供独立“清理缓存”操作。关闭本地保留开关时，界面会先要求确认；确认后会通过后台清理任务删除普通邮箱本地保留数据，并显示清理状态。清理任务会拒绝重复启动、对 SQLite 短暂锁进行有限重试，前端状态轮询使用退避间隔减少长任务压力。更完整的范围说明见 [`docs/local-mail-retention.md`](docs/local-mail-retention.md)。

### Web 应用功能

#### 核心功能
- 🔐 **登录验证** - 密码保护的 Web 界面，支持在线修改密码；忘记密码可用官方脚本 `scripts/reset_login_password.py` 重置（见 [故障排除](docs/troubleshooting.md)）
- 📁 **分组管理** - 支持最多三级树形邮箱分组，创建、编辑、折叠展开、同级排序、跨层级拖拽移动和级联删除
- 🌐 **账号/分组代理** - 每个分组可配置 HTTP/SOCKS5 代理，子分组可继承父级代理，单个账号也可设置代理并优先覆盖分组代理；代理 URL 支持 `{mail}` 占位符（对接 [Resin](https://github.com/Resinat/Resin) 等粘性代理池）
- 📧 **多邮箱管理** - 批量导入和管理 Outlook/Hotmail OAuth / IMAP 邮箱账号
- 🪪 **别名管理** - 支持给单个邮箱配置多个别名邮箱，主邮箱和别名都可用于检索邮件和调用对外 API
- 🔀 **别名高级用法** - 可将外部邮箱自动转发到本项目管理的邮箱 A，再把外部邮箱配置为 A 的别名，从而通过本项目统一读取邮件
- 📬 **邮件查看** - Web 界面支持查看收件箱和垃圾邮件；API 支持 `inbox`、`junkemail`、`deleteditems`、`all`
- 🔗 **邮件分享链接** - 可创建限时或永久的只读分享链接，并可选择只展示收件箱和垃圾邮件合计当前最新 `1–50` 封邮件
- ✉️ **基础写邮件** - 已完成 Graph 授权的 Outlook/Hotmail 账号可在 Web 端以自身身份发送纯文本邮件
- 📎 **附件下载** - 邮件详情支持单个附件下载，也支持将全部附件打包为 ZIP 下载
- 🔍 **全屏查看** - 支持全屏模式查看邮件
- 📤 **导出功能** - 支持按分组树、选中账号或全部导出邮箱账号信息
- 🧩 **WebDAV 备份** - 支持将“导出全部分组”的文件按 Cron 定时上传到 WebDAV，也可手动上传
- 🎨 **现代化 UI** - 四栏布局，账号列表、邮件列表、邮件详情分区清晰
- 🎭 **系统级外观皮肤** - 支持内置 classic、自定义 zip 皮肤包和 Git 仓库来源；切换后所有登录设备一致
- ⚡ **性能优化** - 邮件列表与账号列表缓存，分组切换和账号切换更快
- 📄 **分页加载** - 滚动到底部自动加载下一页（每页20封）
- 🔥 **临时邮箱** - 集成 GPTMail + DuckMail + Cloudflare Temp Email，多提供商生成、导入、读取、查看详情；Cloudflare 支持多渠道配置，每个 Worker/管理员密码/邮件池独立管理，并按渠道查看全部邮件
- ⚙️ **系统设置** - 在线修改密码、API Key、邮件获取超时等
- 🔄 **OAuth2 助手** - 内置授权流程，快速获取 Refresh Token
- 💾 **邮件缓存** - 智能缓存邮件列表，切换即时展示；普通邮箱本地保留默认关闭，可在设置页开启、查看统计并清理本地保留缓存
- 🏷️ **标签管理** - 支持给邮箱打标签、批量操作、按标签筛选
- 🧮 **项目管理** - 按项目维度领取/回报邮箱（独立状态机），入口默认隐藏，可在「设置 → 常规设置」开启后从网页创建项目、查看各状态计数、停用/恢复与删除
- 📦 **批量移动分组** - 批量选择邮箱移动到任意普通分组层级
- ✅ **批量选择** - 邮箱列表、邮件列表均支持全选当前列表与清空选择
- 🗑️ **邮件删除** - 单封/批量永久删除；Graph 与 IMAP（含标准 IMAP 账号、OAuth IMAP 回退）均支持
- 🔄 **API 优先级回退** - Outlook OAuth 默认 Graph API → IMAP(新) → IMAP(旧)；可按账号记录首选通道，失败后仍自动回退并记住实际成功通道
- 🔑 **对外 API** - 通过 API Key 直接获取邮件，无需登录，支持别名邮箱、聚合文件夹和多条件筛选 带+号的附加电子邮箱自动识别，自动回退主邮箱/别名邮箱查询；如果要求的功能比较完善，建议直接对接完整API，文档已经改成了适合AI读取的形状，直接喂给AI让AI按照完整API使用登录密码而不是API Key对接即可

#### 邮件转发
- 📮 **按来源关联通知** - 活跃邮箱按账号或分组配置自动通知，无需额外开启转发
- 📨 **多渠道转发** - 支持多个 SMTP、Telegram、企业微信和飞书目标，按具体邮箱、分组或 CF 域名分别通知
- 👥 **实际收件人** - 转发摘要展示邮件的实际收件人和抄送地址，方便识别别名收信
- 🔎 **关键词筛选** - 可设置每行一个关键词，主题或完整正文命中任一关键词才转发，留空则全部转发
- ⏱️ **时间窗口控制** - 支持仅转发最近 X 分钟内收到的邮件
- 🗑️ **垃圾箱转发可选** - 可配置是否把垃圾邮件一起纳入转发
- 📚 **转发历史** - 支持查看最近转发记录和失败记录
- ▶️ **手动触发** - 支持从界面手动触发一次转发检查

#### Token 刷新管理
- 🔁 **全量刷新** - 一键刷新所有 Outlook/Hotmail OAuth 账号 Token
- 🔄 **轮换结果** - 区分 Token 已更新与验证成功但未轮换，刷新日志持久记录轮换结果，批量完成提示展示两类数量
- 🕒 **刷新时间** - 分别展示最近刷新、最近成功刷新和最近轮换；未轮换也可算刷新成功，失败不覆盖上次成功时间
- ✅ **完整批量操作** - 在 Token 刷新管理列表中可直接批量刷新、复制、导出、转发、代理、打标签、移动分组和删除账号
- 📄 **分页浏览** - Token 刷新管理列表支持页码跳转和每页数量切换，适合大量账号场景
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
1. **分组面板** - 以最多三级树形结构显示所有邮箱分组，点击切换，选中父分组时包含子分组账号
2. **邮箱面板** - 显示当前分组及其子分组下的邮箱账号列表
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

界面中的 OAuth2 助手会读取服务启动时的 `OAUTH_CLIENT_ID` 和 `OAUTH_REDIRECT_URI`。如果你在 Docker / Docker Compose 里配置了自己的值，授权链接和换取 Token 都会使用这些值；如果没有配置，则使用项目内置默认值。账号导入时，Client ID 要和同一次授权换出的 Refresh Token 配套使用。

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

手动 OAuth 助手默认走 GraphAPI 单资源权限，避免 Microsoft OAuth v2 在同一次授权中混用 Graph 和 Outlook 资源时报 `AADSTS70011`：
- `offline_access` - 获取刷新令牌
- `Mail.Read` / `Mail.ReadWrite` / `Mail.Send` / `User.Read` - Graph 读信、邮件管理、以当前账号自身身份发信与基本用户信息

`Mail.Send` 是 Web 端基础写邮件所需的委托权限。历史 Refresh Token 无法静默增加该权限；如果写邮件时提示权限不足，请对该账号重新完成一次 `GraphAPI` 授权。重新授权不会影响已有的读信配置。

如需 IMAP 访问，请在「Outlook邮箱授权」面板选择 `IMAP授权`（自动授权默认是 GraphAPI），不要和 Graph 权限放在同一次手动授权链接里。IMAP 授权不包含 `Mail.Send`，也不支持 Web 端基础写邮件。

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

iCloud 支持 `imap.mail.me.com:993` 和 App 专用密码，并提供独立的 Apple 主号、隐藏邮件地址管理及可选自动重登入口。配置、邮件隔离、备份和降级步骤见 [iCloud 使用说明](docs/icloud.md)。Apple 私有协议与长期续期仍需真实账号验收。

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

支持批量导入，每行一个账号。导入文件格式保持不变；导入弹窗可为新增账号统一设置备注、标签和状态，通知自动使用所在分组的有效规则。普通邮箱导入时不能选择临时邮箱分组。

分组支持最多三级层级。选中父分组时，邮箱账号列表会同时展示该分组和所有子分组下的账号；子分组未配置代理时会向上继承父级分组代理。删除含子分组的分组会级联删除子分组，并把相关账号移回默认分组。

#### 代理与 Resin `{mail}` 模板

分组或账号代理 URL 可包含字面量 `{mail}`。出站请求（拉信、Token 刷新、Outlook 自动授权等）会在运行时替换为邮箱 `@` 前 local-part：去掉非字母数字字符并转小写。配置原样存库，编辑回显不展开。

推荐示例（Resin 默认端口 2260，V1 粘性身份 `Platform.Account:TOKEN`）：

```text
socks5h://outlook.{mail}:你的Token@127.0.0.1:2260
```

Token 为空时以下两种均可：

```text
socks5h://outlook.{mail}:@127.0.0.1:2260
socks5h://outlook.{mail}@127.0.0.1:2260
```

说明：

- 建议优先 `socks5h://` / `socks5://`；普通 HTTP 代理对 IMAP 令牌请求可能不可用
- 不同邮箱前缀净化后可能碰撞（如 `a.b` 与 `ab`），本项目接受该行为
- 上传账号自动授权：优先用上传记录自己的 `proxy_url`，否则继承分组代理模板
- 默认 `LOG_LEVEL=INFO` 会在拉信 / Token 刷新 / 自动授权时打印 `[代理]` 详情（密码打码）。批量场景日志较多时，设 `LOG_LEVEL=WARNING` 即可降噪关闭这类 INFO
- 友情项目：[Resin](https://github.com/Resinat/Resin)

### 3. 查看邮件

1. 从左侧选择分组
2. 选择邮箱账号
3. 点击「获取邮件」按钮
4. 在 Web 界面切换「收件箱」「垃圾邮件」查看邮件
5. 滚动到邮件列表底部自动加载下一页（每页 20 封）
6. 点击邮件查看详情，支持 HTML 渲染与全屏查看
7. 需要查看 `deleteditems` 或 `all` 聚合结果时，建议使用对外 API 或内部 API

#### Web 端基础写邮件

选择一个已启用、通过 `GraphAPI` 授权的 Outlook/Hotmail 主账号后，邮件列表顶部会显示「写邮件」。该功能仅支持以当前账号自身身份向一个或多个收件人发送纯文本邮件：

- 历史账号如提示需要重新授权，请按上文重新完成 `GraphAPI` 授权以获取 `Mail.Send`。
- Microsoft Graph 返回 `202 Accepted` 时，界面会显示“邮件已提交发送”；这表示服务已接受请求，不等同于收件人已送达。
- 发信请求遇到网络超时或连接中断时，系统不会自动重发，以避免重复投递；请先确认结果后再决定是否手动重新发送。
- 当前不支持 IMAP/SMTP 手动发信、临时邮箱、别名或共享邮箱代发、附件、HTML/富文本、草稿、回复/转发、已发送列表、浏览器扩展入口、对外 API、批量、定时或自动化发信。

#### 邮件分享链接

在邮箱账号的分享操作中可创建可撤销的只读链接。创建时可选择「不限量」或「仅最新 N 封」；后者可设置 `1–50`，并将收件箱和垃圾邮件合并后只展示当前最新的 N 封邮件。

- 可选设置访问码：`4–32` 位英文字母或数字，区分大小写；留空或已有的无访问码链接仍可直接访问。设置后，访客须通过验证才能查看邮箱信息、邮件列表和详情。
- 创建成功后可复制链接和访问码。访问码仅在创建时展示，请自行保存；分享管理只显示是否设置访问码，忘记时请取消旧链接后重新创建。
- 同一浏览器会话会记住最近验证的 20 个分享链接；访问码连续输错 5 次后，该 IP 对此链接暂停验证 5 分钟。验证后仍受有效期、撤销状态和邮件数量限制约束。
- 「仅最新 N 封」是动态窗口：新邮件到达后，较旧邮件可能不再通过该链接可见。
- 永不过期的受限链接会持续展示未来最新 N 封邮件；不再需要时请在分享管理中取消链接。
- 限制只约束可访问邮件数量，不会对允许查看的邮件正文、附件元数据等内容进行脱敏。

### 4. 批量选择与批量操作

#### 邮箱账号列表

邮箱账号列表左侧有选择框，适合对多个账号同时刷新 Token、复制邮箱、修改转发状态、打标签、移动分组或删除。

常用选择方式：

1. **单选/取消单选**：点击账号左侧的选择框。
2. **进入批量选择模式**：点击邮箱面板顶部的「☑」按钮。按钮高亮后，可点击账号行来切换选中状态，不必点中选择框。
3. **连续范围选择**：先选中一个账号，再按住 `Shift` 点击另一个账号或选择框，会选中两者之间的连续范围。
4. **拖拽选择**：进入批量选择模式后，在账号行或选择框上按住鼠标/触控板并向上或向下拖动，可连续选中经过的账号；如果起点账号已选中，本次拖拽会批量取消选中经过的账号。
5. **全选当前列表**：点击批量菜单里的「全选」或「全选已加载」。账号列表分页加载时，该按钮只作用于当前已经加载到页面中的账号；继续向下滚动加载更多后，可再次点击全选已加载。
6. **清空选择**：点击「清空选择」取消当前列表中的所有选择。

选中至少一个账号后，会出现批量菜单：

- PC 端：菜单悬浮在第一个选中账号的右侧，并随账号列表滚动重新定位。
- 移动端：菜单显示在底部，便于触控操作。

普通邮箱账号支持的批量操作：

- **刷新 Token**：只对 Outlook/Hotmail OAuth 账号可用；IMAP 账号不可刷新，按钮会按可刷新数量提示。
- **复制邮箱+别名**：复制选中账号的主邮箱和已配置别名。
- **导出**：二次验证后导出选中账号，适合先按标签或搜索筛选后只导出当前勾选的账号。
- **通知配置**：在顶部「更多功能 -> 邮件转发 -> 转发规则」中多选邮箱、分组或 Worker，统一指定通知渠道或关闭通知；手机端入口位于「操作」菜单。
- **标签+ / 标签-**：给选中账号批量添加或移除一个标签。
- **移动**：把选中账号移动到指定分组。
- **启用账号 / 停用账号**：批量修改账号状态，保留密码、Token 和项目记录。停用账号不再参与新的项目领取、Token 刷新和自动转发；需要重新使用时，可在主页选中后批量启用。
- **删除**：永久删除选中账号，操作前会再次确认。

临时邮箱分组也使用同一套选择方式，但批量菜单只显示适用于临时邮箱的操作，例如复制邮箱、标签添加/移除和删除；刷新 Token、移动分组等普通账号专属操作会隐藏。

按分组导出时会包含所选分组及其所有子分组账号；如果同时选中了父分组和子分组，导出内容会自动去重。

#### Token 刷新管理列表

「Token刷新管理」里的邮箱列表也支持同一套批量选择方式：

1. 点击列表头部的「☑」进入批量选择模式。
2. 通过复选框、账号行点击、`Shift` 连续范围选择或拖拽选择账号。
3. 点击「全选当前列表」只选中当前筛选后已经显示的账号。
4. 搜索关键词或切换状态筛选时，已选账号会清空，避免误操作筛选外账号。

选中账号后可直接执行这些批量动作：

- **刷新 Token**：继续使用 Token 刷新管理的流式任务日志，可查看账号级进度和结果。
- **复制邮箱+别名 / 导出**：复用普通邮箱列表的复制和二次验证导出流程。
- **停用账号**：可先筛选刷新失败账号，再勾选需要停用的账号批量操作。停用后会从 Token 刷新管理列表移除，仍可在主页找到并批量启用。
- **代理 / 标签+ / 标签- / 移动 / 删除**：复用普通邮箱账号批量接口，完成后会同步刷新 Token 刷新管理列表、主邮箱列表和分组计数。

#### 邮件列表

普通邮箱的邮件列表左侧也有选择框，适合批量处理当前邮箱的邮件：

1. 点击邮件左侧选择框选中或取消选中单封邮件。
2. 点击「全选」选中当前已加载的邮件列表。
3. 点击「清空选择」取消已选邮件。
4. 点击「设为已读」把选中的未读邮件批量标记为已读；如果所选邮件都已读，该按钮会禁用。
5. 点击「删除」批量永久删除选中邮件，操作前会再次确认。

邮件批量选择只作用于当前邮箱当前文件夹/聚合视图里已经加载的邮件；切换邮箱、刷新邮件列表或列表为空时，已选邮件会被清空。

### 5. 别名管理

1. 打开某个邮箱账号的「编辑账号」
2. 在「别名邮箱」中按行填写多个别名
3. 保存后，主邮箱和别名都会指向同一个账号

适合这些场景：

- 同一账号有多个注册邮箱名称
- 某些站点使用了 `user+tag@example.com`
- 外部邮箱自动转发到本项目管理邮箱后，希望继续用原邮箱名来取信

### 6. 邮件转发

在顶部「更多功能」下拉菜单的「项目管理」下方打开「邮件转发」（手机端为「操作」菜单），也可直接访问 `/forwarding`。转发管理已独立于系统设置，规则、渠道和投递历史以表格展示；轮询参数在「运行设置」中单独保存，邮件筛选条件在各条规则中配置，不会被系统设置保存覆盖。先配置**通知渠道**，再新增**转发规则**，最后通过预览确认通知去向：

1. **通知渠道**：创建具名的 SMTP、Telegram、企业微信或飞书目标。同类型可创建多个目标，一个来源可选多个渠道，也可由多个来源共用一个渠道。凭据加密保存，新渠道表单仅显示已配置标记，留空保留原值；测试使用当前草稿，不自动保存。
2. **普通邮箱来源**：按“具体账号 → 直属及祖先分组 → 普通默认配置”选择最近明确配置。未单独配置的邮箱与子分组自动使用上层配置，无需选择继承或额外开启转发；通知方式可指定渠道或关闭通知。规则列表中的“删除转发规则”删除该来源的独立规则并恢复使用上层配置；删除默认规则后默认不通知。账号仍须处于活跃状态；移组保留自身明确配置，未覆盖则跟随新分组。
3. **CF 来源**：选择 Worker，再配置完整域名或完整收件地址，按“具体地址 → 完整域名 → Worker 默认配置”解析。支持未导入本地的地址；只给某个地址指定渠道即可通知该地址，无需开启整个域名。Worker 默认初始关闭，不继承普通邮箱配置。`example.com` 不自动包含子域名；完整地址保留 `+` 后缀和点，不合并别名。
4. **多选与预览**：邮箱、分组和 Worker 使用可搜索的下拉复选框，可输入邮箱地址或名称筛选并逐项勾选。切换筛选条件保留已选来源，“全选筛选结果”只选择当前匹配项，“清空全部”取消所有选择。规则支持新增、单条编辑和同来源范围批量编辑；新增仍不覆盖已有规则，所选来源中任一已有独立规则时整批拒绝，可直接使用列表铅笔图标编辑。预览可从已选来源中选择具体邮箱或 Worker，查看自动继承路径和实际目标；历史可按来源、完整地址、渠道和状态查询。
5. **规则筛选与批量操作**：规则表格可组合关键词、来源范围、通知渠道和通知方式筛选，刷新后保留条件。逐项勾选或全选当前筛选结果，确认后批量删除；改变筛选条件会清空勾选，避免误删隐藏规则。同一来源范围（例如均为具体普通邮箱，或均为 CF 完整域名）支持批量编辑；在表单勾选要修改的通知方式与渠道、关键词或发件人，未勾选字段保留各自原值，勾选后留空清除条件。编辑固定来源身份；不同类型来源仍可混合删除，任一规则已失效则整批拒绝，写入失败整体回滚，未选规则不变。列表垃圾桶图标带删除提示并保留确认。

每条转发规则可独立配置**邮件关键词**与**来信发件人**，普通邮箱和 CF 均适用。关键词每行一个，主题或完整可见正文包含任意一项即可，不区分大小写。发件人每行一个完整邮箱地址，忽略大小写精确匹配任一发件邮箱，不匹配显示名称或相似后缀。两类条件都填写时必须同时命中，某项留空则不限制；两项均空时转发全部。继承时使用最近明确规则的整套目标和筛选条件，不与上层条件叠加；预览和规则表格均显示生效条件。SMTP 发件地址和目标收件人仍统一由通知渠道配置。

轮询间隔、串行/并行及普通邮箱的时间窗口、垃圾箱选项仍在「运行设置」中独立保存；CF 不套用普通邮箱的文件夹和时间窗口。未匹配规则条件的邮件不会建立投递，但正常推进扫描进度；条件调整不会为已处理邮件自动补发，也不重新筛选已建立的失败投递。

- 同一邮箱的**同一封邮件 + 同一具体通知渠道**只建立一条投递；多条关联、重复扫描和已导入 CF 地址的重复读取不会产生第二条通知。不同新邮件分别通知，同类型不同渠道分别记录结果。
- 一个目标成功、另一个失败时只重试失败目标；重试退避从 30 秒起翻倍，最多 1 小时，并遵守更晚的上游冷却时间。停用目标不会改发到其他渠道，仍有来源引用或未完成投递时不能删除。
- 新关联默认只处理生效后的新邮件，不自动补发历史；普通账号可通过已有转发日志入口明确回退游标，补扫尚未处理的历史邮件，已成功目标仍去重，既有事件不会追加新目标。
- CF 后台按 Worker 分页读取实际收件地址，即使关闭网页也继续工作，不自动创建本地邮箱或写入临时邮件缓存。扫描进度和失败投递持久化；服务重启会继续获取上游保留期内的来信。主动停用 Worker 会暂停扫描和发送，重新启用默认不补发主动停用期间邮件。
- 修改实际收件目的地会取消旧目的地版本的积压，更新同一目标认证信息可继续重试。移除邮箱级覆盖恢复继承，关闭则停止该来源通知。
- 可以手动触发统一检查，并在历史中查看 CF 扫描错误、具体渠道结果及阻塞原因。
- Telegram、企业微信、飞书和 SMTP 的转发摘要会显示实际收件人；邮件有抄送时也会显示抄送地址，缺少收件人信息时显示“未提供”。

升级会幂等迁移旧配置为兼容渠道与具体邮箱规则，不自动生成“普通邮箱默认”规则。原来开启转发的存量账号，各自建立“具体普通邮箱”规则并指定原启用渠道；旧关闭账号保持不通知。`auto` 采用原可用渠道，`none` 保持无通知，显式选择沿用旧入口对 `email/tg/qywx` 等别名及空格的解析。已有自动迁移的普通默认规则会拆分到账号后移除，同时保留渠道生效时间、游标和成功记录；手工新增或修改过的规则不动。规则条件另有一次性升级：旧全局关键词复制到升级前已生效的普通邮箱规则，CF 保持原来不受普通全局关键词限制的行为；新增发件人筛选默认为不限，旧 SMTP 发件地址、目标收件人、凭据及历史投递保持原值。已完成旧版迁移的数据库也会升级，迁移标记与数据同事务提交，失败整体回滚；重启不覆盖用户后续修改。旧关键词接口只同步兼容迁移账号，不修改手工规则。迁移只执行一次，定时检查不重建关联；新导入邮箱仍可自动使用分组规则。CF 不会自动启用。旧设置接口只调整迁移账号的兼容渠道，不改动手工账号、分组或 CF 规则；普通默认配置仍可由用户手动创建。旧 `PUT` 更新接口兼容保留，页面新增使用 `POST`，单条/同范围批量编辑使用按稳定 ID 的 `PATCH`。

需要回退版本时，先停止新调度并备份数据库和密钥。兼容实例的新成功记录与旧 `forward_logs` 同事务同步，可用于旧版本去重；先确认旧设置镜像和兼容渠道选择，再启动旧调度。旧版本无法处理新实例和 CF 通知；恢复迁移前备份会丢失备份后的配置和记录，不应将仅回退程序视为无损数据回滚。

#### 飞书群机器人

1. 在目标飞书群的「设置 -> 机器人」中添加自定义机器人，复制其 `https://open.feishu.cn/open-apis/bot/v2/hook/...` Webhook 地址。
2. 在本项目「更多功能 -> 邮件转发 -> 通知渠道」中新建飞书渠道，填写 Webhook；机器人启用了签名校验时，同时填写签名密钥。
3. 如果机器人使用关键词安全校验，可配置关键词“邮件转发”，测试消息与正式邮件摘要都包含该词；使用 IP 白名单时需允许本服务的出口 IP。
4. 点击「发送测试消息」检查配置，再保存渠道并在「来源关联」中选择它；测试使用当前表单且不会自动保存。活跃普通邮箱与 CF 地址均按有效来源规则自动通知。

Webhook 和签名密钥加密保存，重新打开设置不会回显，留空表示保留已有值。勾选「明确清除已有签名密钥」后，测试立即按无签名配置发送，保存后正式转发也不再使用签名；这不会修改飞书机器人侧的安全设置。

飞书发送纯文本邮件摘要，请求体按 UTF-8 字节限制在 20 KB 以内，超长内容会截断。正式转发与测试共享同一 Webhook 的限速（每秒最多 5 次、每分钟最多 100 次）；飞书返回限流时会记录失败并遵守有效的 `Retry-After`。

转发历史显示飞书业务错误，如签名失败或关键词不匹配；HTTP 200 不等同于发送成功。失败渠道会在后续转发检查中重试，其他已成功渠道不会重复发送。网络中断或超时后可能无法确认飞书是否已接收，后续重试仍可能重复通知，可先检查群消息。

### 7. WebDAV 备份

在「设置 -> WebDAV 备份」中配置：

1. 填写 WebDAV 目录 URL，例如 `https://dav.example.com/backups`
2. 按需填写 WebDAV 用户名和密码 / App Password
3. 填写 5 段 Cron 表达式，例如 `0 3 * * *`
4. 点击「计算下次执行时间」确认 Cron 预览，时间会使用常规设置里的应用时区
5. 点击「测试 WebDAV」验证目录可写；测试只上传临时测试文件，不需要登录密码
6. 修改备份设置时，在“敏感操作确认”中输入登录密码后保存

补充说明：

- 定时备份会上传与“导出全部分组”一致的文本文件，文件名形如 `all_groups_backup_YYYYMMDD_HHMMSS.txt`
- 坚果云需要先创建专用目录，再填写该目录 URL，例如 `https://dav.jianguoyun.com/dav/mailBackup`；不要只填写 `https://dav.jianguoyun.com/dav`
- 「手动上传」会立即上传真实备份文件，需要输入登录密码
- WebDAV 备份涉及账号、令牌、临时邮箱凭据等敏感数据，建议使用专用 WebDAV 目录并控制访问权限

### 8. 浏览器扩展（密码版）

仓库内置 Chrome / Edge Manifest V3 扩展，目录为 `browser-extension/`。扩展使用 Web 端登录密码，不需要对外 API Key。

安装方式：

1. 打开浏览器扩展管理页，例如 `chrome://extensions/` 或 `edge://extensions/`
2. 开启开发者模式
3. 选择“加载已解压的扩展程序”
4. 选择本仓库的 `browser-extension` 目录

使用方式：

1. 点击扩展图标
2. 填写 OutlookEmail 服务地址和 Web 登录密码
3. 点击“保存配置”，或直接点侧边栏里的功能入口

扩展会在浏览器侧边栏内提供原生操作面板，当前网页标签不会被切走。现在可直接使用邮箱、导入、刷新、Token、导出、标签和设置等功能。完整安装、配置、功能和故障排查说明见 [浏览器扩展使用说明](browser-extension/README.md)。

### 9. 对外 API

通过 API Key 直接获取邮件，无需登录 Web 界面。

当前额外支持：

- 使用主邮箱或别名邮箱取信
- `folder=all` 一次聚合收件箱和垃圾邮件并按标准化后的邮件时间倒序排序，`top` 按每个文件夹分别计算
- 支持按主题、发件人、关键词筛选列表
- 支持特殊字符别名，例如 `user+alias@example.com`
- 查询 `@gmail.com` / `@googlemail.com` 地址时，原后缀未命中会自动回退到另一个后缀
- 默认 `top=1`
- `skip` / `top` 会做安全解析：非数字使用默认值，负数按 `0` 处理；`top` 最大 `50`

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
| [🎭 外观皮肤](docs/skins.md) | 系统级皮肤、zip 上传、Git 仓库来源、皮肤包格式与持久化说明 |
| [📡 API 文档](docs/api.md) | 对外简易API、完整API、代理配置 |
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
- [Resin](https://github.com/Resinat/Resin) — 高性能粘性代理池网关
- [icloud-mail](https://github.com/t508708/icloud-mail) — iCloud Mail 协议参考；部分实现基于其 MIT 许可代码改编，详见 [第三方许可说明](third_party/icloud-mail-LICENSE.txt)

## ⭐ Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=assast/outlookEmail&type=Date)](https://star-history.dera.page/#assast/outlookEmail&type=Date)

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！你的 Star 是我持续更新的动力！** ⭐

初次维护一个项目，2026年04月11日15:45:33才发现有几个pull没合并，非常抱歉，这是我的联系方式如果我没看到的话，可以提醒我一下，有好的建议也可以提，感谢~
邮箱：u3794336@outlook.com

## 免责声明
本项目仅供学习、研究和技术交流使用，请遵守相关平台和服务条款，不要用于违规、滥用或非法用途。
因使用本项目产生的任何风险和后果，由使用者自行承担。
