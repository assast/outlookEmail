# OAuth IMAP 权限修复说明

## 问题描述

在之前的版本中，通过 OAuth 授权获得的 RefreshToken 无法用于 IMAP 方式获取邮件，即使导出的账号文件中包含了 RefreshToken。

## 问题原因

OAuth 授权时只申请了 Microsoft Graph API 的权限：

```python
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read"
]
```

**核心问题**：RefreshToken 的权限作用域由授权时申请的 Scope 决定。由于授权时没有申请 IMAP 权限（`https://outlook.office.com/IMAP.AccessAsUser.All`），导致该 RefreshToken 无法换取具有 IMAP 访问权限的 AccessToken。

### 技术细节

1. **RefreshToken 本质**：RefreshToken 是一个凭据，用于换取 AccessToken
2. **权限绑定**：RefreshToken 只能换取授权时申请的 Scope 对应的 AccessToken
3. **IMAP 访问要求**：使用 IMAP 访问邮箱需要特定的 Scope：`https://outlook.office.com/IMAP.AccessAsUser.All`

当使用只有 Graph API 权限的 RefreshToken 去请求 IMAP scope 的 AccessToken 时，Microsoft 会返回权限不足错误。

## 解决方案

在 OAuth 授权配置中添加 IMAP 权限：

```python
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "https://outlook.office.com/IMAP.AccessAsUser.All"  # 新增 IMAP 权限
]
```

## 升级说明

### 新用户

新授权的账号会自动获得 IMAP 访问权限，导出的 RefreshToken 可以同时用于：
- Microsoft Graph API 访问
- IMAP 协议访问

### 现有用户

**已授权的账号需要重新授权才能获得 IMAP 访问权限**。

#### 重新授权步骤：

1. 在账号列表中找到需要更新的账号
2. 点击账号的"重新授权"按钮
3. 完成新的 OAuth 授权流程
4. 新的 RefreshToken 将同时具备 Graph API 和 IMAP 权限

#### 识别需要更新的账号：

如果你的账号在使用 IMAP 获取邮件时遇到权限错误（如 `IMAP_TOKEN_FAILED`、`invalid_scope` 等），说明该账号需要重新授权。

## 技术实现

### 代码位置

- 配置文件：`outlook_web/segments/01_bootstrap.py`
- IMAP 获取邮件：`outlook_web/segments/03_mail_helpers.py`

### IMAP Token 获取流程

```python
# 定义 IMAP 所需的 Scope
IMAP_TOKEN_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"

# 使用 RefreshToken 换取 IMAP AccessToken
def request_imap_token_response(client_id: str, refresh_token: str, ...):
    return post_with_proxy_fallback(
        TOKEN_URL_IMAP,
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": IMAP_TOKEN_SCOPE  # 必须有此 Scope
        },
        ...
    )
```

## 权限说明

| Scope | 用途 | 是否必需 |
|-------|------|---------|
| `offline_access` | 允许获取 RefreshToken | ✅ 必需 |
| `https://graph.microsoft.com/Mail.Read` | Graph API 读取邮件 | ✅ 必需 |
| `https://graph.microsoft.com/Mail.ReadWrite` | Graph API 读写邮件 | ✅ 必需 |
| `https://graph.microsoft.com/User.Read` | Graph API 读取用户信息 | ✅ 必需 |
| `https://outlook.office.com/IMAP.AccessAsUser.All` | IMAP 协议访问 | ✅ 新增必需 |

## 常见问题

### Q: 为什么需要同时支持 Graph API 和 IMAP？

A: 两种方式各有优势：
- **Graph API**：功能丰富，支持高级查询和操作
- **IMAP**：标准协议，兼容性好，某些场景下更稳定

同时支持两种方式可以提供更好的兼容性和灵活性。

### Q: 现有账号不重新授权会有什么影响？

A: 现有账号可以继续使用 Graph API 获取邮件，但无法使用 IMAP 方式。如果你的应用场景只使用 Graph API，可以不重新授权。

### Q: 如何验证账号是否有 IMAP 权限？

A: 可以通过以下方式验证：
1. 尝试使用 IMAP 方式获取邮件，如果成功则有权限
2. 检查授权时间，在此次修复后授权的账号都包含 IMAP 权限

## 相关资源

- [Microsoft Graph API 文档](https://learn.microsoft.com/en-us/graph/api/overview)
- [OAuth 2.0 授权流程](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-auth-code-flow)
- [Outlook IMAP 文档](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth)
