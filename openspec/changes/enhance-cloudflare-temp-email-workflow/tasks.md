## 1. 后端测试

- [x] 1.1 为 Cloudflare 批量生成添加测试：数量范围、禁用渠道、成功写入渠道归属、部分失败响应和全部失败响应。
- [x] 1.2 为 Cloudflare 批量生成标签绑定添加测试：存在的标签写入 `temp_email_tags`，不存在的标签被忽略。
- [x] 1.3 为 Cloudflare 临时邮箱导入添加测试：`[cloudflare:<channel_name>]`、`email----jwt----channel_name`、旧 `email----jwt` 默认渠道、导入不存在渠道。
- [x] 1.4 为 Cloudflare 临时邮箱导入标签绑定添加测试：新增和更新成功的邮箱都会绑定本次提交的有效标签。
- [x] 1.5 为 AI 用户名设置和测试生成添加测试：API Key 加密保存、不明文回显、留空保留、明确清空、测试生成成功和上游失败。
- [x] 1.6 为 AI 用户名批量生成添加测试：AI 候选清洗去重、数量不足随机补齐、AI 失败回退并在响应中标明。

## 2. 后端实现

- [x] 2.1 增加临时邮箱标签 ID 归一化和绑定辅助函数，复用 `tags` 与 `temp_email_tags`。
- [x] 2.2 新增 Cloudflare 批量生成 API，接收 `count`、`channel_id`、`domain`、`tag_ids`，返回成功邮箱列表、失败数量和失败明细。
- [x] 2.3 将批量生成成功的 Cloudflare 临时邮箱绑定到所选渠道和有效标签，并保持现有单个生成 API 兼容。
- [x] 2.4 扩展 `/api/temp-emails/import` 接收 `tag_ids`，在 Cloudflare 导入新增或更新成功后绑定有效标签。
- [x] 2.5 保持 Cloudflare 导入渠道只来自文本格式或默认渠道，不新增导入默认渠道参数。
- [x] 2.6 增加 AI 用户名设置读写逻辑，API Key 使用已有加密设置能力，读取设置时只返回配置状态或掩码。
- [x] 2.7 新增 AI 用户名测试生成接口，使用 `requests` 调用 OpenAI-compatible `/chat/completions` 并返回清洗后的用户名列表。
- [x] 2.8 实现 AI 用户名候选生成、解析、清洗、去重和随机回退逻辑，并接入 Cloudflare 批量生成流程。

## 3. 前端实现

- [x] 3.1 更新临时邮箱生成弹窗：Cloudflare 模式显示数量输入、渠道、域名、标签选择和批量创建状态。
- [x] 3.2 更新生成提交流程：Cloudflare 批量创建调用新 API，显示成功数量、失败数量和失败摘要，并刷新临时邮箱列表。
- [x] 3.3 更新导入弹窗：临时邮箱导入保留标签选择；选择 Cloudflare 提供商时展示 `[cloudflare:<channel_name>]` 和 `email----jwt----channel_name` 示例。
- [x] 3.4 确保导入弹窗不新增 Cloudflare 渠道选择控件，渠道指定只通过导入文本格式完成。
- [x] 3.5 在 Cloudflare 设置区增加 AI 用户名生成配置表单、保存逻辑和测试生成按钮，API Key 留空时保留已有值。

## 4. 验证

- [x] 4.1 运行相关后端测试：`python3 -m pytest tests/test_cloudflare_channels.py` 或项目当前测试命令。
- [x] 4.2 运行覆盖设置和前端静态检查的现有测试，确认没有破坏普通账号导入、标签管理和单个临时邮箱生成。
- [x] 4.3 手动验证 Cloudflare 导入提示展示渠道文本示例，且界面没有新增导入渠道选择控件。
- [x] 4.4 手动验证 Cloudflare 批量生成：普通随机生成、AI 成功生成、AI 失败回退、标签绑定和部分失败提示。
