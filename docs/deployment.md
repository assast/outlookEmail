# 🚀 部署指南

## 方式一：使用 Windows `exe`

从 GitHub Releases 下载对应版本的 `OutlookEmail-windows-x64-*.zip`，解压后直接运行 `OutlookEmail.exe`。

**桌面版首次启动会自动：**
- 创建本地数据目录
- 初始化数据库
- 自动生成并持久化 `SECRET_KEY`

**Windows 默认数据目录：**
- `%APPDATA%\OutlookEmail`

默认访问地址仍为 `http://127.0.0.1:5000`。

## 方式二：使用 Docker（推荐服务器部署）

直接使用 GitHub Actions 自动构建的镜像，无需本地构建：

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

# 查看日志
docker logs -f outlook-mail-reader

# 停止容器
docker stop outlook-mail-reader
docker rm outlook-mail-reader
```

**首次启动会自动：**
- 创建数据目录
- 初始化数据库
- 创建默认分组和临时邮箱分组
- 设置默认密码（admin123）

## 方式三：使用 Python 直接运行

```bash
# 克隆仓库
git clone https://github.com/assast/outlookEmail.git
cd outlookEmail

# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export LOGIN_PASSWORD=admin123
export SECRET_KEY=your-secret-key-here
export PORT=5000

# 运行应用
python web_outlook_app.py
```

访问 `http://localhost:5000` 即可使用。
服务器部署建议始终显式设置固定 `SECRET_KEY`。

## 运行模式说明

服务需要保持单 worker 运行。Token 刷新管理里的流式任务、导出验证等短期任务使用进程内状态保存；如果自定义部署成多个 worker，POST 初始化任务和后续 SSE 订阅可能落到不同进程，导致任务不存在或过期。

官方 Docker 镜像已固定为 Gunicorn 单 worker，并通过线程处理慢请求：

```bash
gunicorn -k gthread -w 1 --threads ${GUNICORN_THREADS:-4} ...
```

如需调整并发，请优先调整 `GUNICORN_THREADS`，不要增加 worker 数。

## 使用 Docker Compose

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
      - GPTMAIL_API_KEY=your-api-key
    restart: unless-stopped
```

```bash
# 启动服务
docker-compose up -d

# 查看定时任务启动日志（应出现“定时任务已启动”）
docker-compose logs -f

# 停止服务
docker-compose down
```

## 定时刷新说明

- 应用在 `python web_outlook_app.py`、Docker、Docker Compose、Gunicorn 单 worker 模式下都会自动初始化定时任务。
- 如需确认定时任务是否已启动，可执行 `docker-compose logs -f`，日志中应出现“定时任务已启动”。
- 在独立页面 `/refresh-strategy` 选择按到期刷新、旧周期全量刷新或停用。到期模式每天凌晨 2 点检查 RT 到期窗口，默认只刷新预计 7 天内到期的账号；未轮换的 RT 保持原锚点并在下一次调度中继续尝试。
- 旧周期模式继续读取通用设置中的 `enable_scheduled_refresh`、`use_cron_schedule`、`refresh_cron` 和 `refresh_interval_days`，每次 Cron 触发执行全量刷新；按天方式每天检查一次，到达全局周期后才执行。固定周期模式可能错过微软的令牌轮换窗口。
- 新旧策略互斥。没有 `refresh_strategy_mode` 的存量实例沿用旧定时开关：开启时默认按到期刷新，关闭时保持停用。选择到期或停用模式后，旧开关会关闭并永久退役，不能再选择或启用旧模式；旧 Cron 和周期值保留。存量旧开关已关闭的实例也不能重新启用旧模式。刷新策略模式保存在应用的设置键值表中，不需要新增 SQL 升级脚本。
- Docker 界面更新本身不会执行 `docs/sql` 脚本；新容器启动时应用会自动添加可空到期锚点列。若使用自定义启动流程而没有运行应用初始化，可备份数据库后手动执行 [2026-11-21-add-outlook-refresh-token-expiry.sql](sql/2026-11-21-add-outlook-refresh-token-expiry.sql)，不要在自动升级已添加该列后重复执行。应用会使用可信的 RT 更新时间或轮换日志补算；无法确认签发时间的账号保持未知，默认纳入每日刷新。

## 环境变量配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | Session 密钥（服务器部署强烈建议固定设置） | Windows `exe` 首次启动会自动生成并持久化；Docker / Python / 生产环境请显式设置固定值，不要随意修改，否则会导致已存储敏感数据无法解密 |
| `LOGIN_PASSWORD` | 登录密码 | `admin123` |
| `FLASK_ENV` | 运行环境 | `production` |
| `LOG_LEVEL` | 全局日志级别（`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`）。默认 `INFO` 会输出出站 `[代理]` 详情（含 Resin Platform/Account，密码已打码）。批量拉信或 Token 刷新时日志较多，生产环境若只需告警可设 `LOG_LEVEL=WARNING` 降噪 | `INFO` |
| `PORT` | 应用端口 | `5000` |
| `HOST` | 监听地址 | `0.0.0.0` |
| `DATABASE_PATH` | 数据库路径 | `data/outlook_accounts.db` |
| `GPTMAIL_BASE_URL` | GPTMail API 地址 | `https://mail.chatgpt.org.uk` |
| `GPTMAIL_API_KEY` | GPTMail API Key | `gpt-test` |
| `DUCKMAIL_BASE_URL` | DuckMail API 地址 | `https://api.duckmail.sbs` |
| `DUCKMAIL_API_KEY` | DuckMail API Key | 空 |
| `CLOUDFLARE_WORKER_DOMAIN` | Cloudflare Temp Email Worker 域名，也兼容读取 `WORKER_DOMAIN` | 空 |
| `CLOUDFLARE_EMAIL_DOMAINS` | Cloudflare 临时邮箱域名列表，逗号分隔，也兼容读取 `EMAIL_DOMAIN` | 空 |
| `CLOUDFLARE_ADMIN_PASSWORD` | Cloudflare 管理密码，也兼容读取 `ADMIN_PASSWORD` | 空 |
| `OAUTH_CLIENT_ID` | OAuth 客户端 ID | `建议使用自己的，如果实在搞不到不填的话会使用默认的` |
| `OAUTH_REDIRECT_URI` | OAuth 重定向 URI | `建议使用自己的，如果实在搞不到不填的话会使用默认的` |

**生成 SECRET_KEY：**
```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

## 数据持久化

数据库文件存储在 `./data` 目录中，通过 Docker Volume 挂载实现持久化。

自定义外观皮肤文件存储在数据库文件同目录下的 `skins/` 目录。默认数据库路径是 `data/outlook_accounts.db` 时，皮肤目录为 `data/skins/`。Docker 部署应继续挂载整个 `./data:/app/data`，不要只备份单个数据库文件，否则自定义皮肤文件会丢失并回退到内置 `classic` 皮肤。

数据库包含以下表：
- `settings` - 系统设置（登录密码、API Key 等）
- `groups` - 邮箱分组
- `accounts` - Outlook 邮箱账号
- `account_refresh_logs` - 账号刷新记录
- `temp_emails` - 临时邮箱
- `temp_email_messages` - 临时邮箱的邮件

## 端口映射

默认映射 5000 端口，可以在 `docker-compose.yml` 中修改：

```yaml
ports:
  - "8080:5000"  # 将容器的 5000 端口映射到主机的 8080 端口
```

## 镜像说明

项目使用 GitHub Actions 自动构建并推送 Docker 镜像，支持稳定版、开发版和正式版本标签。

### 可用镜像标签

- `ghcr.io/assast/outlookemail:latest` - 默认分支最近一次符合条件的稳定构建
- `ghcr.io/assast/outlookemail:main` - `main` 分支最近一次符合条件的构建
- `ghcr.io/assast/outlookemail:dev` - `dev` 分支最近一次符合条件的构建
- `ghcr.io/assast/outlookemail:vX.Y.Z` - 指定正式版本镜像，由手动发版工作流生成

补充说明：

- 文档改动不会触发 Docker 镜像重建
- 正式发版时建议优先使用 `vX.Y.Z` 明确版本标签
- 具体发版流程见仓库根目录的 `RELEASE.md`

### 更新镜像

```bash
docker pull ghcr.io/assast/outlookemail:latest
docker-compose down
docker-compose up -d
```

### 自己构建镜像（可选）

```bash
docker build -t outlook-mail-reader .
docker run -d \
  --name outlook-mail-reader \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e LOGIN_PASSWORD=admin123 \
  outlook-mail-reader
```

## 生产环境部署

### 使用 Nginx + HTTPS

**1. 安装 Nginx**
```bash
sudo apt install nginx certbot python3-certbot-nginx -y
```

**2. 配置 Nginx** `/etc/nginx/sites-available/outlook-mail-reader`
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持（如果需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**3. 启用配置**
```bash
sudo ln -s /etc/nginx/sites-available/outlook-mail-reader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

如果生成的邮件分享链接仍使用容器或本地地址，可在 Web「系统设置 → 常规设置」中填写分享链接公网地址，例如 `https://your-domain.com`。留空时，应用会按当前请求的 Host 和协议生成链接；配置值只包含根域名，不包含路径。

**4. 配置 HTTPS**
```bash
sudo certbot --nginx -d your-domain.com
```

### 使用 Caddy（更简单）

```bash
sudo apt install caddy -y

# 配置 /etc/caddy/Caddyfile
your-domain.com {
    reverse_proxy localhost:5000
}

# 重载（自动 HTTPS）
sudo systemctl reload caddy
```
