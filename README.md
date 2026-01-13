# Outlook 邮件管理工具

一个功能完整的 Outlook 邮件管理解决方案，支持多种方式读取 Outlook 邮箱邮件，并提供 Web 界面进行邮箱账号管理和邮件查看。

## ✨ 功能特性

### 邮件读取方式
本工具支持三种方式读取 Outlook 邮箱邮件：

1. **旧版 IMAP 方式** - 使用 `outlook.office365.com` 服务器
2. **新版 IMAP 方式** - 使用 `outlook.live.com` 服务器
3. **Graph API 方式** - 使用 Microsoft Graph API

### Web 应用功能
- 🔐 **登录验证** - 密码保护的 Web 界面
- 📁 **分组管理** - 支持创建、编辑、删除邮箱分组
- 📧 **多邮箱管理** - 批量导入和管理多个 Outlook 邮箱账号
- 📬 **邮件查看** - 查看收件箱邮件列表和邮件详情
- 📤 **导出功能** - 支持按分组导出邮箱账号信息
- 🎨 **现代化 UI** - 简洁美观的四栏式界面布局
- ⚡ **性能优化** - 邮箱列表缓存，快速切换分组

### 界面布局
Web 应用采用四栏式布局设计：
1. **分组面板** - 显示所有邮箱分组，点击切换
2. **邮箱面板** - 显示当前分组下的邮箱账号列表
3. **邮件列表** - 显示选中邮箱的收件箱邮件
4. **邮件详情** - 显示选中邮件的完整内容

## 📋 系统要求

- Python 3.8+
- 网络连接（访问 Microsoft 服务）

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行 Web 应用

```bash
python web_outlook_app.py
```

启动后访问：http://127.0.0.1:5001

默认登录密码：`admin123`（可在 [`web_outlook_app.py`](web_outlook_app.py:27) 中修改 `LOGIN_PASSWORD` 变量）

### 3. 运行命令行测试工具

```bash
python outlook_mail_reader.py
```

## 📁 项目结构

```
outlookEmail/
├── outlook_mail_reader.py    # 命令行邮件读取测试工具
├── web_outlook_app.py        # Flask Web 应用
├── requirements.txt          # Python 依赖
├── README.md                 # 项目说明文档
└── templates/
    ├── index.html            # Web 应用主页面
    └── login.html            # 登录页面
```

## 📖 使用说明

### 导入邮箱账号

在 Web 界面中，点击「导入邮箱」按钮，按以下格式输入账号信息：

```
邮箱----密码----client_id----refresh_token
```

支持批量导入，每行一个账号。

### 获取 OAuth2 凭证

要使用本工具，您需要获取以下 OAuth2 凭证：

1. **Client ID** - Microsoft Azure 应用注册的客户端 ID
2. **Refresh Token** - OAuth2 刷新令牌

获取方式：
1. 在 [Azure Portal](https://portal.azure.com/) 注册应用
2. 配置适当的 API 权限（Mail.Read、IMAP.AccessAsUser.All 等）
3. 通过 OAuth2 授权流程获取 refresh_token

### API 端点

Web 应用提供以下 API 端点：

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/groups` | GET | 获取所有分组 |
| `/api/groups` | POST | 创建分组 |
| `/api/groups/<id>` | PUT | 更新分组 |
| `/api/groups/<id>` | DELETE | 删除分组 |
| `/api/accounts` | GET | 获取所有账号 |
| `/api/accounts` | POST | 添加账号 |
| `/api/accounts/<id>` | GET | 获取账号详情 |
| `/api/accounts/<id>` | PUT | 更新账号 |
| `/api/accounts/<id>` | DELETE | 删除账号 |
| `/api/emails/<email>` | GET | 获取邮件列表 |
| `/api/email/<email>/<message_id>` | GET | 获取邮件详情 |
| `/api/groups/<id>/export` | GET | 导出分组邮箱 |
| `/api/accounts/export` | GET | 导出所有邮箱 |

## ⚙️ 配置说明

### Web 应用配置

在 [`web_outlook_app.py`](web_outlook_app.py) 中可以修改以下配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `LOGIN_PASSWORD` | `admin123` | 登录密码 |
| `DATABASE` | `outlook_accounts.db` | SQLite 数据库文件 |
| `IMAP_SERVER_OLD` | `outlook.office365.com` | 旧版 IMAP 服务器 |
| `IMAP_SERVER_NEW` | `outlook.live.com` | 新版 IMAP 服务器 |
| `IMAP_PORT` | `993` | IMAP 端口 |

### 命令行工具配置

在 [`outlook_mail_reader.py`](outlook_mail_reader.py) 中配置：

| 配置项 | 说明 |
|--------|------|
| `EMAIL` | 邮箱地址 |
| `PASSWORD` | 邮箱密码 |
| `CLIENT_ID` | OAuth2 客户端 ID |
| `REFRESH_TOKEN` | OAuth2 刷新令牌 |
| `PROXY` | 代理地址（可选） |

## 🔒 安全说明

- 请妥善保管您的 OAuth2 凭证
- 建议修改默认登录密码
- 数据库文件包含敏感信息，请注意保护
- 生产环境建议使用 HTTPS

## 📝 依赖说明

- **Flask** >= 3.0.0 - Web 框架
- **Werkzeug** >= 3.0.0 - WSGI 工具库
- **requests** >= 2.25.0 - HTTP 请求库

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License