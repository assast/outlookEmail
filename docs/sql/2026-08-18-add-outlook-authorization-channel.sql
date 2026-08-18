-- 为 Outlook OAuth 账号记录首选/最近成功的邮件授权通道。
-- 空值表示历史未知或用户主动清空；不根据旧凭证回填。

ALTER TABLE accounts
    ADD COLUMN authorization_type TEXT NOT NULL DEFAULT '';
