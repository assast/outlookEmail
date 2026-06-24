# Release Notes - v2.0.73

## 🎉 Cloudflare 临时邮箱功能增强

发布日期：2026-06-25

---

## ✨ 新增功能

### 1. **兼容旧格式导入**

- 自动识别并提取 `邮箱----JWT` 格式中的邮箱地址
- 无需手动修改旧版本导出的文件
- 平滑的迁移体验，零学习成本

**使用场景**: 直接粘贴旧导出文件内容，系统自动兼容处理

### 2. **管理员 API 连接测试**

- 在 Cloudflare 渠道设置页新增"测试连接"按钮
- 一键验证渠道配置是否正确
- 详细的测试报告：
  - ✅ 获取域名列表
  - ✅ 获取地址列表
  - ✅ 获取邮件列表
- 显示样本数据，确认 API 可用性

**使用场景**: 配置新渠道后立即测试，避免配置错误导致后续问题

### 3. **自动导入实时进度显示**

- 大数据量导入时显示实时进度
- 显示信息：
  - 导入进度：已导入/总数 (百分比)
  - 详细统计：新增、更新、跳过数量
  - 当前页数
- 使用 Server-Sent Events (SSE) 流式技术
- 完成后显示完整汇总

**使用场景**: 从 Cloudflare 渠道自动拉取数百或数千个邮箱地址

---

## 🔧 技术改进

### API 增强

- **新增接口**: `POST /api/cloudflare/channels/<id>/test`
  - 测试 Cloudflare 渠道管理员 API 连接
  - 返回三项测试的详细结果

- **增强接口**: `POST /api/temp-emails/import-cloudflare-addresses`
  - 新增 `stream=true` 参数支持流式进度返回
  - 使用 Server-Sent Events 实时推送进度

### 导入格式兼容性

**新格式** (推荐):
```
user1@example.com
user2@example.com
```

**旧格式** (自动兼容):
```
user1@example.com----eyJhbGciOi...
user2@example.com----eyJhbGciOi...
```

系统会自动提取邮箱部分，忽略 JWT。

### 防护机制

- 自动导入最多处理 100 页
- 最大记录数：50,000 条
- 防止无限循环或内存溢出

---

## 📊 测试覆盖

- **28 个测试全部通过** ✅
- 新增测试：
  - `test_channel_connection_test_validates_configuration_and_calls_admin_api`
  - 旧格式兼容性测试更新

---

## 📖 文档更新

- 更新 API 文档 (`docs/api.md`)
  - 新增测试接口说明
  - 标注导入格式兼容性
  - 更新自动导入接口参数

---

## 🎯 用户体验提升

### 之前
- ❌ 旧导出文件需要手动删除 JWT 部分
- ❌ 配置错误只能通过实际使用才能发现
- ❌ 大量导入时界面"卡住"，不知道是否正常

### 现在
- ✅ 直接粘贴旧文件，自动兼容
- ✅ 配置后立即测试，问题一目了然
- ✅ 实时进度显示，心中有数

---

## 🔄 升级说明

### 数据库迁移
- 无需数据库迁移
- 兼容现有数据

### 配置变更
- 无需配置变更
- 新功能向后兼容

### 破坏性变更
- 无破坏性变更
- 完全向后兼容

---

## 🐛 已知问题

无

---

## 📦 安装/升级

### 从 Git 升级
```bash
git pull origin main
git checkout v2.0.73
pip install -r requirements.txt
```

### 从 Docker 升级
```bash
docker pull your-registry/outlook-email:2.0.73
docker-compose up -d
```

---

## 💬 反馈

如有问题或建议，请通过以下方式反馈：
- GitHub Issues: https://github.com/assast/outlookEmail/issues
- Email: [your-email]

---

## 👨‍💻 贡献者

感谢所有为本次发布做出贡献的开发者！

---

## 📅 下一版本计划

- 更多临时邮箱提供商支持
- 批量操作优化
- 性能提升

---

**完整更改日志**: https://github.com/assast/outlookEmail/compare/v2.0.72...v2.0.73
