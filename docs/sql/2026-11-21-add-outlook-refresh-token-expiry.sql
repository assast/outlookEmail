-- Outlook Refresh Token 到期锚点
-- 在现有 accounts 表添加可空到期时间；不修改任何 Refresh Token。
ALTER TABLE accounts ADD COLUMN refresh_token_expires_at TEXT;
