# Outlook 邮件阅读器 - Docker 部署指南

## 📦 快速开始

### 使用预构建镜像（推荐）

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
- 创建默认分组
- 设置默认密码（admin123）

### 使用 Docker Compose

修改 `docker-compose.yml` 使用预构建镜像：

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
      - FLASK_ENV=production
    restart: unless-stopped
```

然后启动服务：

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 🔧 配置说明

### 环境变量

在 `docker-compose.yml` 中可以配置以下环境变量：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | Session 密钥（建议修改） | `outlook-mail-reader-secret-key-change-in-production` |
| `LOGIN_PASSWORD` | 登录密码 | `admin123` |
| `FLASK_ENV` | 运行环境 | `production` |
| `DATABASE_PATH` | 数据库路径 | `data/outlook_accounts.db` |
| `GPTMAIL_BASE_URL` | GPTMail API 地址 | `https://mail.chatgpt.org.uk` |
| `GPTMAIL_API_KEY` | GPTMail API Key | `gpt-test` |
| `GPTMAIL_API_KEY` | GPTMail API Key | `gpt-test` |

### 数据持久化

数据库文件存储在 `./data` 目录中，通过 Docker Volume 挂载实现持久化。

### 端口映射

默认映射 5000 端口，可以在 `docker-compose.yml` 中修改：

```yaml
ports:
  - "8080:5000"  # 将容器的 5000 端口映射到主机的 8080 端口
```

## 🚀 镜像说明

项目使用 GitHub Actions 自动构建并推送 Docker 镜像到 `ghcr.io/assast/outlookemail:latest`。

### 可用镜像标签

- `ghcr.io/assast/outlookemail:latest` - 最新的主分支构建（推荐）
- `ghcr.io/assast/outlookemail:main` - main 分支最新版本
- `ghcr.io/assast/outlookemail:master` - master 分支最新版本

### 更新镜像

```bash
# 拉取最新镜像
docker pull ghcr.io/assast/outlookemail:latest

# 重启容器
docker-compose down
docker-compose up -d
```

### 自己构建镜像（可选）

如果需要修改代码或自定义构建：

```bash
# 构建镜像
docker build -t outlook-mail-reader .

# 运行自己构建的镜像
docker run -d \
  --name outlook-mail-reader \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e LOGIN_PASSWORD=admin123 \
  outlook-mail-reader
```

## 🌐 生产环境部署

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
    }
}
```

**3. 启用配置**
```bash
sudo ln -s /etc/nginx/sites-available/outlook-mail-reader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**4. 配置 HTTPS**
```bash
sudo certbot --nginx -d your-domain.com
```

### 使用 Caddy（更简单）

```bash
# 安装 Caddy
sudo apt install caddy -y

# 配置 /etc/caddy/Caddyfile
your-domain.com {
    reverse_proxy localhost:5000
}

# 重载（自动 HTTPS）
sudo systemctl reload caddy
```

## 🔐 安全配置

### 1. 修改默认密码

在 `docker-compose.yml` 中：
```yaml
environment:
  - LOGIN_PASSWORD=your_secure_password_here
```

### 2. 配置防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 3. 限制访问来源（Nginx）

```nginx
location / {
    allow 192.168.1.0/24;  # 允许内网
    deny all;               # 拒绝其他
    proxy_pass http://localhost:5000;
}
```

## 🛠️ 故障排查

### 容器状态 unhealthy

容器显示 `unhealthy` 通常是因为健康检查失败。

**解决方法：**

```bash
# 1. 查看健康检查日志
docker inspect outlook-mail-reader | grep -A 10 Health

# 2. 手动测试
docker exec outlook-mail-reader curl -f http://localhost:5000/login

# 3. 使用最新镜像重启
docker pull ghcr.io/assast/outlookemail:latest
docker-compose down
docker-compose up -d
```

### 502 错误（Nginx）

**原因：** 应用未正常启动

**解决方法：**

```bash
# 1. 检查容器状态
docker ps

# 2. 查看应用日志
docker-compose logs

# 3. 测试应用是否响应
curl http://localhost:5000/login

# 4. 重新拉取镜像并重启
docker pull ghcr.io/assast/outlookemail:latest
docker-compose down
docker-compose up -d
```

**正确的日志应该显示：**
```
[INFO] Starting gunicorn 21.2.0
[INFO] Listening at: http://0.0.0.0:5000
[INFO] Using worker: sync
[INFO] Booting worker with pid: 7
```

### 数据库表不存在错误

**错误信息：** `sqlite3.OperationalError: no such table: settings`

**原因：** 数据库未初始化

**解决方法：**

```bash
# 方法 1：删除旧数据库，重新初始化
docker-compose down
rm -rf data/outlook_accounts.db
docker-compose up -d

# 方法 2：手动初始化数据库
docker exec outlook-mail-reader python -c "from web_outlook_app import init_db; init_db()"
docker-compose restart

# 方法 3：使用最新镜像
docker pull ghcr.io/assast/outlookemail:latest
docker-compose down
docker-compose up -d
```

### 数据库问题

```bash
# 重置数据库
docker-compose down
rm ./data/outlook_accounts.db
docker-compose up -d
```

## 🔄 更新应用

### 更新到最新版本

```bash
# 拉取最新镜像
docker pull ghcr.io/assast/outlookemail:latest

# 重启服务
docker-compose down
docker-compose up -d

# 或使用 Docker 命令
docker stop outlook-mail-reader
docker rm outlook-mail-reader
docker run -d \
  --name outlook-mail-reader \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e LOGIN_PASSWORD=admin123 \
  ghcr.io/assast/outlookemail:latest
```

## 📚 相关文档

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [GitHub Actions 文档](https://docs.github.com/actions)
