# OAuth IMAP 权限优化 - 快速指南

## 问题概述

**现象**：邮箱 OAuth 授权成功后，导出的文件包含 RefreshToken，但无法使用 IMAP 方式获取邮件。

**原因**：授权时只申请了 Graph API 权限，未包含 IMAP 访问权限。

## 解决方案

已在最新版本中修复，OAuth 授权现在会同时申请 IMAP 权限。

## 升级指南

### 新用户
无需任何操作，新授权的账号自动获得 IMAP 权限。

### 现有用户（重要）

**已授权的账号需要重新授权才能获得 IMAP 权限。**

#### 重新授权步骤：

1. 登录 Web 界面
2. 在账号列表中找到需要更新的账号
3. 点击账号操作菜单中的"重新授权"按钮
4. 在弹出的 OAuth 对话框中完成授权流程：
   - 点击"生成授权链接"
   - 在浏览器中打开授权链接并完成授权
   - 复制授权后的回调 URL
   - 粘贴到"授权后的 URL"输入框
   - 点击"换取 Token"
   - 点击"保存"更新账号

5. 完成！现在该账号可以同时使用 Graph API 和 IMAP 访问邮件

#### 如何判断需要重新授权？

如果你的账号在使用 IMAP 获取邮件时遇到以下错误，说明需要重新授权：
- `IMAP_TOKEN_FAILED`
- `invalid_scope`
- `AADSTS70000`
- `consent_required`

## 技术细节

### 新增的权限

在 OAuth 授权时新增了以下权限：
```
https://outlook.office.com/IMAP.AccessAsUser.All
```

### 完整权限列表

授权后的 RefreshToken 将包含以下权限：

1. `offline_access` - 获取 RefreshToken
2. `https://graph.microsoft.com/Mail.Read` - Graph API 读取邮件
3. `https://graph.microsoft.com/Mail.ReadWrite` - Graph API 读写邮件
4. `https://graph.microsoft.com/User.Read` - Graph API 读取用户信息
5. `https://outlook.office.com/IMAP.AccessAsUser.All` - IMAP 协议访问（新增）

## 常见问题

### Q: 现有账号不重新授权会怎样？

A: 现有账号可以继续使用 Graph API 获取邮件，但无法使用 IMAP 方式。如果你的使用场景只用 Graph API，可以不重新授权。

### Q: 如何验证账号是否有 IMAP 权限？

A: 最简单的方法是尝试使用 IMAP 方式获取邮件，如果成功则有权限。也可以通过查看账号的授权时间，在本次修复（commit ea73d29）之后授权的账号都包含 IMAP 权限。

### Q: 为什么需要同时支持 Graph API 和 IMAP？

A: 两种方式各有优势：
- **Graph API**: 功能丰富，支持高级查询和操作，但某些场景下可能受限于 API 配额
- **IMAP**: 标准协议，兼容性好，某些场景下更稳定，不受 API 配额限制

同时支持两种方式可以提供更好的灵活性和可靠性。

### Q: 重新授权会影响现有邮件数据吗？

A: 不会。重新授权只更新账号的授权凭证（RefreshToken），不会影响已存储的邮件数据和账号配置。

## 验证方法

### 方法1：通过测试脚本验证配置

```bash
python tests/test_oauth_imap_scope.py
```

应该看到所有测试通过，并显示包含 5 个权限的配置。

### 方法2：通过授权链接验证

1. 在 Web 界面点击"获取 Token"
2. 点击"生成授权链接"
3. 查看生成的授权链接中的 `scope` 参数
4. 应该包含 `https://outlook.office.com/IMAP.AccessAsUser.All`

### 方法3：通过实际使用验证

使用新 RefreshToken 进行 IMAP 访问，不应再出现权限错误。

## 更多信息

- 详细技术文档：[oauth-imap-scope-fix.md](oauth-imap-scope-fix.md)
- 优化总结：[oauth-imap-optimization-summary.md](oauth-imap-optimization-summary.md)
- 变更日志：[CHANGELOG.md](../CHANGELOG.md)

## 支持

如有问题，请查阅上述详细文档或提交 Issue。
