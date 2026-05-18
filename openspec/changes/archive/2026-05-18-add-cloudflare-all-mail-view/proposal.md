## 背景与动机

Cloudflare Temp Email 已经提供管理员邮件列表接口，可以查看整个 Worker 收到的邮件池；但本项目目前只能在选中某个本地临时邮箱后，通过该邮箱保存的 JWT 查看单个地址的邮件。用户需要在本项目里查看 Cloudflare 全部邮件，并且在查询 Gmail 地址时兼容同一邮箱可能以 `@gmail.com` 或 `@googlemail.com` 出现的情况。

## 变更内容

- 基于当前配置的一套 Cloudflare Temp Email Worker 和管理员密码，新增 Cloudflare 全局邮件列表能力。
- Cloudflare 全局邮件列表支持可选的收件地址过滤，同时保留不带过滤条件的“全部邮件”视图。
- 将 Cloudflare 返回的原始 RFC822 邮件解析为现有邮件列表和详情视图可复用的数据形状。
- 当指定邮箱查询未命中时，新增确定性的 `@gmail.com` / `@googlemail.com` 后缀回退。
- 保留现有 plus-address 回退行为，并让它与 Gmail 后缀回退组合工作。
- 响应中返回请求地址、实际查询或解析地址、是否使用回退等元数据。

## 能力范围

### 新增能力

- `cloudflare-all-mail-view`：通过配置好的 Cloudflare Temp Email 管理员邮件 API 查看和过滤全部邮件。
- `email-address-fallback-resolution`：通过现有 plus-address 回退和新增 Gmail/Googlemail 后缀回退解析邮箱查询。

### 修改能力

- 无。

## 影响范围

- 后端 Cloudflare 临时邮箱路由：`outlook_web/segments/06_routes_temp_email.py`。
- 现有账号解析辅助函数：`outlook_web/segments/02_groups_accounts.py`。
- 内部和对外邮件 API：`outlook_web/segments/08_forwarding_scheduler_errors.py`。
- 临时邮箱前端：`static/js/index/03-temp-emails.js`，以及必要的样式和模板。
- API 文档 `docs/api.md` 和 README 用户说明。
- 测试覆盖 Cloudflare 管理员邮件列表、地址过滤回退，以及现有 plus-address 回退兼容性。
