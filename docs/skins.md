# 外观皮肤

外观皮肤是系统级设置。登录后切换的皮肤会保存到服务端 `settings` 表里的 `active_skin_id`，所有设备和浏览器会使用同一套当前皮肤。

## 使用入口

1. 登录 Web 界面。
2. 打开「设置」。
3. 进入「外观皮肤」。
4. 选择已有皮肤，或通过 zip 上传、Git 仓库安装自定义皮肤。

内置皮肤 ID 是 `classic`。当当前配置的皮肤不存在、格式无效或 CSS 读取失败时，前端会自动回退到 `classic`，并在皮肤列表里记录错误信息。

## 皮肤包格式

皮肤包根目录必须包含 `skin.json`，并至少包含一个 CSS 入口文件。

```json
{
  "id": "midnight-sample",
  "name": "Midnight Sample",
  "version": "1.0.0",
  "entry": "theme.css",
  "description": "Sample dark skin using OutlookEmail CSS variables",
  "preview": "preview.png"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 皮肤 ID，只能使用小写字母、数字、下划线和短横线，最长 64 个字符；不能使用 `classic` |
| `name` | 是 | 显示名称 |
| `version` | 是 | 皮肤版本 |
| `entry` | 是 | CSS 入口文件路径，必须指向包内 `.css` 文件 |
| `description` | 否 | 皮肤说明 |
| `preview` | 否 | 预览图片路径，支持 `png`、`jpg`、`jpeg`、`gif`、`webp` |

仓库内提供了示例皮肤：[`docs/skin-example`](skin-example)。

## CSS 变量

自定义皮肤主要通过覆盖 CSS 变量改变界面外观。当前支持的核心变量包括：

```css
:root {
    --skin-app-bg: #ffffff;
    --skin-surface: #ffffff;
    --skin-surface-muted: #fafafa;
    --skin-surface-soft: #f8fafc;
    --skin-surface-hover: #f0f0f0;
    --skin-border: #e5e5e5;
    --skin-border-strong: #d9dce3;
    --skin-text: #1a1a1a;
    --skin-text-muted: #666666;
    --skin-text-soft: #64748b;
    --skin-primary: #1a1a1a;
    --skin-primary-hover: #111827;
    --skin-primary-text: #ffffff;
    --skin-accent: #2563eb;
    --skin-accent-soft: #eff6ff;
    --skin-accent-border: #bfdbfe;
    --skin-danger: #dc3545;
    --skin-shadow: rgba(15, 23, 42, 0.08);
    --skin-overlay: rgba(0, 0, 0, 0.4);
}
```

当前版本只完成第一批核心区域变量化。少量细节颜色仍可能由基础样式控制，深色皮肤需要在实际页面中检查对比度和可读性。

## zip 上传

上传文件必须是 zip 包，包根目录应直接包含 `skin.json`。服务端会执行以下校验：

- zip 文件最大 5 MB。
- CSS 文件最大 200 KB。
- 预览图片最大 1 MB。
- 拒绝绝对路径、路径穿越和符号链接。
- 拒绝脚本、HTML、可执行文件等不允许的文件类型。
- 只安装通过 `skin.json` 校验的皮肤。

上传同 ID、同来源的皮肤会覆盖旧版本；如果同一个 ID 已经由其他来源安装，会拒绝安装。

## Git 仓库来源

Git 来源适合把皮肤做成独立仓库。仓库根目录需要包含 `skin.json` 和 CSS 入口文件。

设置页填写：

- Git 仓库地址，例如 `https://github.com/user/outlook-skin.git`
- 可选 ref，例如分支名、tag 或 commit 可解析的 ref

服务端使用 `git clone --depth 1` 拉取仓库。安装或更新失败时不会改变当前启用皮肤，也不会覆盖现有皮肤文件。

注意：

- 运行环境必须安装 `git`。
- 私有仓库凭据没有专门管理入口；不要在多人可见环境中把凭据直接写进 URL。
- Git 安装会让服务器主动访问指定仓库地址，建议只给可信管理员开放设置入口。

## 文件存储与备份

皮肤文件保存在数据库文件同目录下的 `skins/` 目录。例如默认数据库是 `data/outlook_accounts.db` 时，皮肤目录是：

```txt
data/skins/
```

Docker 部署时，如果已按推荐方式挂载 `./data:/app/data`，数据库和皮肤文件会一起持久化。备份或迁移时应同时保留：

- `outlook_accounts.db`
- `skins/`

只备份数据库会保留当前皮肤 ID，但不会保留自定义皮肤文件；恢复后会回退到 `classic`。

## 安全边界

皮肤系统只负责加载 CSS，不执行皮肤包里的脚本或安装命令。服务端会拒绝常见脚本和 HTML 文件。

仍需注意：

- CSS 可以改变界面视觉、隐藏元素或加载远程资源。
- 自定义皮肤应视为可信管理员配置，不适合允许普通用户上传。
- 如果部署在多人共用环境，建议通过网络访问控制或反向代理限制设置页访问来源。
