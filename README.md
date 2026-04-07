# Outlook 邮件管理工具

一个功能完整的 Outlook 邮件管理解决方案，支持多种方式读取 Outlook 邮箱邮件，并提供 Web 界面进行邮箱账号管理和邮件查看。集成 GPTMail + DuckMail + Cloudflare Temp Email 多提供商临时邮箱（支持自建接入），支持一键生成或自定义域名/用户名临时邮箱

## ✨ 功能特性

### 邮件读取方式
本工具支持三种方式读取 Outlook 邮箱邮件：

1. **旧版 IMAP 方式** - 使用 `outlook.office365.com` 服务器
2. **新版 IMAP 方式** - 使用 `outlook.live.com` 服务器
3. **Graph API 方式** - 使用 Microsoft Graph API（推荐）

### Web 应用功能

#### 核心功能
- 🔐 **登录验证** - 密码保护的 Web 界面，支持在线修改密码
- 📁 **分组管理** - 支持创建、编辑、删除邮箱分组，自定义分组颜色，支持分组级别代理设置
- 🌐 **分组代理** - 每个分组可配置 HTTP/SOCKS5 代理
- 📧 **多邮箱管理** - 批量导入和管理多个 Outlook 邮箱账号
- 📬 **邮件查看** - 查看收件箱、垃圾邮件和已删除邮件
- 🔍 **全屏查看** - 支持全屏模式查看邮件
- 📤 **导出功能** - 支持按分组或全部导出邮箱账号信息
- 🎨 **现代化 UI** - 简洁美观的四栏式界面布局
- ⚡ **性能优化** - 智能缓存机制，快速切换分组和邮箱
- 📄 **分页加载** - 滚动到底部自动加载下一页（每页20封）
- 🔥 **临时邮箱** - 集成 GPTMail + DuckMail + Cloudflare Temp Email 多提供商，支持一键生成或自定义域名/用户名
- ⚙️ **系统设置** - 在线修改密码、API Key 等
- 🔄 **OAuth2 助手** - 内置授权流程，快速获取 Refresh Token
- 💾 **邮件缓存** - 智能缓存邮件列表，切换即时展示
- 🏷️ **标签管理** - 支持给邮箱打标签、批量操作、按标签筛选
- 📦 **批量移动分组** - 批量选择邮箱移动到指定分组
- 🗑️ **邮件删除** - 单封/批量永久删除邮件
- 🔄 **API 优先级回退** - Graph API → IMAP(新) → IMAP(旧) 自动回退
- 🔑 **对外 API** - 通过 API Key 直接获取邮件，无需登录（⭐ 新增 2026年02月23日23:52:46）

#### Token 刷新管理
- 🔁 **全量刷新** - 一键刷新所有账号 Token
- ⏰ **定时刷新** - 支持按天数或 Cron 表达式配置，Docker / Docker Compose 启动也会自动生效
- 📊 **刷新统计** - 实时显示失败邮箱数量
- 📜 **刷新历史** - 近半年完整记录

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

## 📦 快速开始

## 🌿 版本管理与发布

本项目采用轻量化双分支版本管理：

- `main`：稳定分支，只保留可发布版本
- `dev`：开发分支，日常功能开发与修复默认在这里进行

版本号遵循语义化版本（Semantic Versioning）：

- `v1.0.0`：首个稳定正式版
- `v1.0.1`：向后兼容的问题修复
- `v1.1.0`：向后兼容的新功能
- `v2.0.0`：包含不兼容变更的大版本

仓库中的版本相关文件：

- `VERSION`：当前仓库内定义的版本号
- `CHANGELOG.md`：版本变更记录
- Git Tag：正式发布标签，如 `v1.0.0`

推荐发布流程：

1. 在 `dev` 分支完成开发与验证
2. 合并到 `main`
3. 更新 `VERSION` 与 `CHANGELOG.md`
4. 在 `main` 上打正式标签，例如 `v1.0.0`

Docker 镜像标签约定：

- `ghcr.io/assast/outlookemail:latest`：默认稳定版（来自默认分支）
- `ghcr.io/assast/outlookemail:dev`：开发分支最新构建
- `ghcr.io/assast/outlookemail:v1.0.0`：正式版本镜像

### 方式一：使用 Docker（推荐）

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

### 方式二：使用 Python 直接运行

```bash
git clone https://github.com/assast/outlookEmail.git
cd outlookEmail
pip install -r requirements.txt
export SECRET_KEY=your-secret-key-here
python web_outlook_app.py
```

访问 `http://localhost:5000` 即可使用。

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

## 📖 使用说明

### 1. 获取 OAuth2 凭证

要使用本工具，您需要获取以下 OAuth2 凭证：

1. **Client ID** - Microsoft Azure 应用注册的客户端 ID
2. **Refresh Token** - OAuth2 刷新令牌

#### 步骤 1：注册 Azure 应用

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

在 Web 界面中，点击「导入邮箱」按钮，按以下格式输入账号信息：

```
邮箱----密码----client_id----refresh_token
```

也支持在 Web 导入弹窗中切换为：

```
邮箱----密码----refresh_token----client_id
```

示例：
```
user@outlook.com----password123----24d9a0ed-8787-4584-883c-2fd79308940a----0.AXEA...
```

支持批量导入，每行一个账号。**注意：导入邮箱时不能选择临时邮箱分组。**

### 3. 查看邮件

1. 从左侧选择分组
2. 选择邮箱账号
3. 点击「获取邮件」按钮
4. 切换「收件箱」、「垃圾邮件」或「已删除」标签查看不同文件夹的邮件
5. 滚动到邮件列表底部自动加载下一页（每页20封）
6. 点击邮件查看详情（支持 HTML 渲染）
7. 点击「🔍 全屏查看」按钮查看完整邮件内容

### 4. 对外 API（⭐ 新增）

通过 API Key 直接获取邮件，无需登录 Web 界面。

**配置步骤：**
1. 点击「⚙️ 设置」→ 在「对外 API Key」处点击「🔑 随机生成」→ 保存

**调用示例：**
```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox"
```

详细文档见 [API 文档](docs/api.md)。

## 📚 详细文档

| 文档 | 说明 |
|------|------|
| [🚀 部署指南](docs/deployment.md) | Docker、Docker Compose、Nginx/Caddy 部署、环境变量配置 |
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
- **Requests** - HTTP 客户端
- **IMAP4_SSL** - IMAP 协议支持
- **Microsoft Graph API** - Outlook 邮件 API

### 前端技术栈
- **原生 JavaScript** - 无框架依赖
- **CSS3** - 现代化样式
- **Fetch API** - 异步请求
- **DOMPurify 3.0.8** - HTML 净化

### 系统要求
- Python 3.8+
- SQLite 3
- Docker（可选）
- 2GB+ 内存

## 📝 依赖说明

```txt
flask>=3.0.0
flask-wtf>=1.2.0          # CSRF 防护（推荐安装）
werkzeug>=3.0.0
requests>=2.25.0
APScheduler>=3.10.0       # 定时任务
croniter>=1.3.0           # Cron 表达式解析
bcrypt>=4.0.0             # 密码哈希
cryptography>=41.0.0      # 数据加密
```

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

- [Microsoft Graph API](https://docs.microsoft.com/graph/)
- [GPTMail](https://mail.chatgpt.org.uk)
- [Flask](https://flask.palletsprojects.com/)

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=assast/outlookEmail&type=Date)](https://star-history.com/#assast/outlookEmail&Date)

---

**⭐ 如果这个项目对你有帮助，请给个 Star 支持一下！你的 Star 是我持续更新的动力！** ⭐
