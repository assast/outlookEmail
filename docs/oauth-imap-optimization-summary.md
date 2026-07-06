# OAuth IMAP 权限优化总结

## 问题分析

用户报告：邮箱授权成功后，导出的文件包含 RefreshToken，但无法使用 IMAP 获取邮件。

### 根本原因

OAuth 授权时只申请了 Microsoft Graph API 的权限，未包含 IMAP 访问权限：

```python
# 修改前的配置
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read"
]
```

**核心问题**：RefreshToken 的权限作用域在授权时确定，无法换取超出授权范围的 AccessToken。由于授权时未申请 IMAP 权限，导致导出的 RefreshToken 无法用于 IMAP 访问。

## 解决方案

### 1. 配置修改

在 `outlook_web/segments/01_bootstrap.py` 中添加 IMAP 权限：

```python
# 修改后的配置
OAUTH_SCOPES = [
    "offline_access",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "https://outlook.office.com/IMAP.AccessAsUser.All"  # 新增
]
```

### 2. 文档更新

- **CHANGELOG.md**: 记录了本次修改和重要提示
- **docs/oauth-imap-scope-fix.md**: 详细的技术文档和升级指南

### 3. 测试验证

创建 `tests/test_oauth_imap_scope.py` 验证配置正确性：

- ✅ IMAP 权限已配置
- ✅ offline_access 已配置
- ✅ Graph Mail.Read 权限已配置
- ✅ Graph Mail.ReadWrite 权限已配置
- ✅ Graph User.Read 权限已配置
- ✅ 权限数量正确: 5 个
- ✅ 无重复权限
- ✅ 所有权限格式有效

## 影响范围

### 新用户
- 新授权的账号自动获得 IMAP 访问权限
- 导出的 RefreshToken 可同时用于 Graph API 和 IMAP 访问

### 现有用户
- **需要重新授权**才能获得 IMAP 访问权限
- 重新授权步骤：
  1. 找到需要更新的账号
  2. 点击"重新授权"按钮
  3. 完成新的 OAuth 授权流程

## 技术细节

### IMAP Token 获取流程

```python
# outlook_web/segments/03_mail_helpers.py

IMAP_TOKEN_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"

def request_imap_token_response(client_id: str, refresh_token: str, ...):
    return post_with_proxy_fallback(
        TOKEN_URL_IMAP,
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": IMAP_TOKEN_SCOPE  # 需要授权时包含此权限
        },
        ...
    )
```

### 授权链接生成

```python
# outlook_web/segments/07_routes_oauth_settings_external.py

@app.route('/api/oauth/auth-url', methods=['GET'])
def api_get_oauth_auth_url():
    params = {
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(OAUTH_SCOPES),  # 使用全局配置
        "state": "12345"
    }
    # ...
```

### Token 交换

```python
# outlook_web/segments/07_routes_oauth_settings_external.py

def exchange_oauth_code_for_tokens(redirected_url: str):
    token_data = {
        "client_id": OAUTH_CLIENT_ID,
        "code": auth_code,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": " ".join(OAUTH_SCOPES)  # 使用全局配置
    }
    # ...
```

## 权限说明

| Scope | 用途 | 状态 |
|-------|------|------|
| `offline_access` | 获取 RefreshToken | 原有 |
| `https://graph.microsoft.com/Mail.Read` | Graph API 读取邮件 | 原有 |
| `https://graph.microsoft.com/Mail.ReadWrite` | Graph API 读写邮件 | 原有 |
| `https://graph.microsoft.com/User.Read` | Graph API 读取用户信息 | 原有 |
| `https://outlook.office.com/IMAP.AccessAsUser.All` | IMAP 协议访问 | **新增** |

## 验证方法

1. **通过测试验证**：
   ```bash
   python tests/test_oauth_imap_scope.py
   ```

2. **通过实际授权验证**：
   - 在 Web 界面生成新的授权链接
   - 授权链接中应包含所有 5 个权限
   - 完成授权后导出的 RefreshToken 应同时支持 Graph API 和 IMAP

3. **通过日志验证**：
   - 使用新 RefreshToken 进行 IMAP 访问时不应出现权限错误
   - 错误码如 `invalid_scope`、`AADSTS70000` 等应不再出现

## 相关文件

### 修改的文件
- `outlook_web/segments/01_bootstrap.py` - OAuth Scope 配置
- `CHANGELOG.md` - 变更日志

### 新增的文件
- `docs/oauth-imap-scope-fix.md` - 详细文档
- `tests/test_oauth_imap_scope.py` - 自动化测试

### 未修改但相关的文件
- `outlook_web/segments/03_mail_helpers.py` - IMAP token 获取逻辑
- `outlook_web/segments/07_routes_oauth_settings_external.py` - OAuth 授权和 token 交换
- `outlook_web/segments/11_routes_graph_oauth.py` - Graph OAuth 自动提取

## 后续建议

1. **用户通知**: 建议在系统更新后通知现有用户重新授权以获得 IMAP 权限
2. **文档完善**: 在用户手册中添加权限说明和重新授权指南
3. **监控指标**: 关注重新授权率和 IMAP 访问成功率
4. **错误提示**: 考虑在检测到 IMAP 权限不足时给出友好的重新授权提示

## 参考资源

- [Microsoft Graph API 文档](https://learn.microsoft.com/en-us/graph/api/overview)
- [OAuth 2.0 授权流程](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-auth-code-flow)
- [Outlook IMAP OAuth 认证](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth)
- [Microsoft Identity Platform Scopes](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-permissions-and-consent)
