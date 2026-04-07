# 🛠️ 故障排查与常见问题

## 故障排查

### 容器无法启动

**检查步骤：**

```bash
# 1. 查看容器状态
docker ps -a

# 2. 查看应用日志
docker logs outlook-mail-reader

# 3. 检查端口占用
lsof -i :5000

# 4. 重新拉取镜像并重启
docker pull ghcr.io/assast/outlookemail:latest
docker-compose down
docker-compose up -d
```

**正确的日志应该显示：**
```
============================================================
Outlook 邮件 Web 应用已初始化
数据库文件: data/outlook_accounts.db
GPTMail API: https://mail.chatgpt.org.uk
============================================================
```

### 数据库表不存在错误

**错误信息：** `sqlite3.OperationalError: no such table: settings`

**原因：** 数据库未初始化或损坏

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

### 无法获取邮件

**可能原因：**
1. Refresh Token 过期或无效
2. Client ID 错误
3. API 权限不足
4. 网络连接问题

**解决方法：**

1. **重新获取 Refresh Token** - 使用内置的 OAuth2 助手重新获取
2. **检查 API 权限** - 确保已添加所需的 API 权限
3. **查看详细错误** - 打开浏览器开发者工具（F12），查看 Network 标签

### 502 错误（Nginx）

**原因：** 应用未正常启动或端口配置错误

```bash
docker ps
docker-compose logs
curl http://localhost:5000/login
sudo nginx -t
docker-compose restart
sudo systemctl reload nginx
```

### 临时邮箱功能不可用

1. **更新 API Key** - 在「⚙️ 设置」中更新 GPTMail API Key
2. **检查服务状态** - 访问 GPTMail 官网确认服务状态

### Session 过期问题

1. **设置 SECRET_KEY 环境变量（必须）**
   ```yaml
   environment:
     - SECRET_KEY=your-fixed-secret-key-here
   ```
   使用 `python -c 'import secrets; print(secrets.token_hex(32))'` 生成

2. 默认 Session 有效期为 7 天，重启应用不会导致 Session 失效（使用固定 SECRET_KEY）

### 数据库锁定错误

**错误信息：** `sqlite3.OperationalError: database is locked`

```bash
docker-compose restart
lsof data/outlook_accounts.db
cp data/outlook_accounts.db data/outlook_accounts.db.backup
docker-compose down
docker-compose up -d
```

---

## 常见问题

### Q: 为什么无法获取邮件？
A: 请检查：(1) Refresh Token 是否有效 (2) Client ID 是否正确 (3) Azure 应用 API 权限 (4) 网络连接 (5) 尝试重新获取 Token

### Q: 如何获取 Refresh Token？
A: 使用内置 OAuth2 助手：点击「获取 Token」→「生成授权链接」→ 浏览器授权 → 复制授权后 URL → 粘贴换取 Token

### Q: 临时邮箱功能如何使用？
A: 点击「临时邮箱」分组 → 「生成临时邮箱」→ 选择邮箱 →「获取邮件」

### Q: 如何修改登录密码？
A: (1) Web 界面：「⚙️ 设置」中修改 (2) 环境变量：`LOGIN_PASSWORD`

### Q: 数据存储在哪里？
A: SQLite 数据库 `data/outlook_accounts.db`，建议定期备份

### Q: 支持哪些邮件文件夹？
A: 收件箱（Inbox）、垃圾邮件（Junk Email）、已删除邮件（Deleted Items）

### Q: 如何批量导入邮箱？
A: 默认格式：`邮箱----密码----client_id----refresh_token`，每行一个；也支持在导入弹窗中切换为 `邮箱----密码----refresh_token----client_id`

### Q: 如何导出邮箱账号？
A: (1) 导出单个分组 (2) 导出所有 (3) 导出选中分组

### Q: Docker 容器无法启动怎么办？
A: (1) `docker logs outlook-mail-reader` (2) 检查端口 (3) 检查目录权限 (4) 拉取最新镜像
