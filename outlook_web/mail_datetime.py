"""Mail date parsing utilities shared by segmented app bootstrap and helpers."""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional


RFC_INTERNALDATE_RE = re.compile(r'^\d{1,2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$')
ISO_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T')
TRAILING_ZONE_NAME_RE = re.compile(r'\s+\([A-Za-z0-9_./+-]+\)$')


def parse_mail_datetime(value: str) -> Optional[datetime]:
    """解析常见邮件日期格式，返回本地无时区 datetime。"""
    if not value:
        return None
    try:
        value_str = str(value).strip()
        value_str = TRAILING_ZONE_NAME_RE.sub('', value_str)
        if ISO_DATETIME_RE.match(value_str):
            parsed = datetime.fromisoformat(value_str.replace('Z', '+00:00'))
        elif RFC_INTERNALDATE_RE.match(value_str):
            parsed = datetime.strptime(value_str, '%d-%b-%Y %H:%M:%S %z')
        else:
            parsed = parsedate_to_datetime(value_str)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        return None
