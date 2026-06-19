## Why

Cloudflare 临时邮箱批量生成当前把 AI 用户名生成隐藏在提交阶段，用户看不到也不能编辑最终使用的用户名，容易造成生成结果不可控。把 AI 生成改为显式按钮，并让用户名以多行文本参与提交，可以让用户在创建前检查、修改或粘贴自定义用户名列表。

## What Changes

- Cloudflare 临时邮箱生成弹窗中，用户名从单行输入改为多行文本，一行一个用户名。
- 在用户名区域右侧新增“AI生成”按钮，点击后按当前“数量”请求 AI 生成对应数量的用户名，并直接覆盖多行文本内容。
- 提交创建时，若用户名文本为空，则按数量随机生成；若用户名文本非空，则有效用户名行数必须严格等于数量，否则直接报错。
- **BREAKING** Cloudflare 批量创建提交阶段不再隐式调用 AI；AI 只由“AI生成”按钮触发。
- AI 生成结果数量不足、数量过多或清洗后不等于请求数量时直接报错，不自动随机补齐。

## Capabilities

### New Capabilities

- `cloudflare-explicit-ai-username-generation`: 管理 Cloudflare 生成弹窗中的显式 AI 用户名生成按钮、多行用户名输入和严格数量校验。

### Modified Capabilities

- `cloudflare-channel-management`: Cloudflare 批量创建支持显式用户名列表，并在用户名列表非空时要求数量严格匹配。

## Impact

- 前端 UI：更新 `static/js/index/03-temp-emails.js` 中 Cloudflare 生成弹窗的用户名输入区域和提交逻辑。
- 后端 API：扩展 `/api/temp-emails/generate-batch` 支持 `usernames` 列表，并新增或复用 AI 用户名生成接口供按钮调用。
- 行为变化：批量创建接口不再在提交时自动 AI 生成；随机生成只在未提交用户名列表时发生。
- 测试：补充后端严格数量校验、AI 生成数量不匹配、前端按钮和多行输入的静态/行为测试。
