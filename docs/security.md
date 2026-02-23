# 🔐 安全配置

## 1. 修改默认密码

**方式一：通过环境变量**

在 `docker-compose.yml` 中：
```yaml
environment:
  - LOGIN_PASSWORD=your_secure_password_here
  - SECRET_KEY=your-random-secret-key-here
```

**方式二：通过 Web 界面**

登录后点击「⚙️ 设置」按钮，在线修改登录密码。

## 2. 启用 CSRF 防护（推荐）

CSRF 防护默认启用，如果未安装 flask-wtf，系统会优雅降级：

```bash
pip install flask-wtf>=1.2.0
```

**CSRF 防护特性：**
- 自动为所有状态变更操作添加 CSRF Token
- 防止跨站请求伪造攻击
- 对用户完全透明，无需手动操作
- 未安装时自动降级，不影响功能使用

## 3. 登录速率限制

系统内置登录速率限制，防止暴力破解：

- **失败次数限制**：5 次失败后锁定
- **锁定时长**：15 分钟
- **基于 IP**：每个 IP 独立计数
- **自动解锁**：锁定时间到期后自动解锁

## 4. 敏感数据加密

所有敏感数据都经过加密存储：

**加密内容：**
- Refresh Token（Fernet 对称加密）
- 登录密码（bcrypt 哈希）
- 邮箱密码（Fernet 对称加密）
- 对外 API Key（Fernet 对称加密）

**加密密钥：**
- 基于 SECRET_KEY 派生加密密钥
- 使用 PBKDF2HMAC 密钥派生函数
- 100,000 次迭代，SHA256 算法

**重要提示：**
- SECRET_KEY 必须设置且保持不变
- 更改 SECRET_KEY 会导致无法解密已存储的数据
- 如需更改，请先导出账号，更改后重新导入

## 5. 导出功能二次验证

导出功能需要密码确认，防止未授权导出：

**保护机制：**
- 导出前需要输入登录密码
- 一次性验证 Token，使用后立即失效
- 所有导出操作记录审计日志
- 记录操作时间、IP 地址和导出详情

**审计日志：**
```sql
SELECT * FROM audit_logs WHERE action = 'export' ORDER BY created_at DESC;
```

## 6. XSS 防护

多层 XSS 防护机制：

**前端防护：**
- 用户输入自动转义（escapeHtml）
- 邮件内容使用 DOMPurify 净化
- iframe 沙箱隔离（sandbox="allow-same-origin"）

**后端防护：**
- 输入净化函数（sanitize_input）
- HTML 特殊字符转义
- 长度限制和控制字符过滤

**DOMPurify 配置：**
```javascript
DOMPurify.sanitize(content, {
    ALLOWED_TAGS: ['a', 'b', 'i', 'u', 'strong', 'em', 'p', 'br', 'div', ...],
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', ...],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', ...]
});
```

## 7. 配置防火墙

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 5000/tcp
sudo ufw enable
```

## 8. 限制访问来源（Nginx）

```nginx
location / {
    allow 192.168.1.0/24;
    deny all;
    proxy_pass http://localhost:5000;
}
```

## 9. 使用强密码

- 登录密码至少 8 位，包含大小写字母、数字和特殊字符
- **SECRET_KEY 必须设置**，使用随机生成的长字符串（至少 32 字节）
- 生成方法：`python -c 'import secrets; print(secrets.token_hex(32))'`
- 定期更换密码

## 10. 数据备份

```bash
# 备份数据库
cp data/outlook_accounts.db data/outlook_accounts.db.backup

# 定期备份（crontab）
0 2 * * * cp /path/to/data/outlook_accounts.db /path/to/backup/outlook_accounts.db.$(date +\%Y\%m\%d)
```

## 安全最佳实践

1. **必须设置 SECRET_KEY**：使用随机生成的强密钥
2. **启用 HTTPS**：生产环境使用 SSL/TLS 加密
3. **定期更新**：及时更新到最新版本
4. **监控日志**：定期查看审计日志和应用日志
5. **限制访问**：使用防火墙和 Nginx 限制访问来源
6. **备份数据**：定期备份数据库文件
7. **强密码策略**：使用复杂密码并定期更换
8. **安装 CSRF 防护**：`pip install flask-wtf`
