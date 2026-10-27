"""Shared recipient evidence and pagination for managed hidden addresses."""

import email
from email.utils import getaddresses
import time


RECIPIENT_HEADERS = ('To', 'Cc', 'Delivered-To', 'X-Original-To')


def message_recipient_headers(message):
    return {name: message.get_all(name, []) for name in RECIPIENT_HEADERS}


def recipient_addresses(item):
    if isinstance(item, (bytes, bytearray)):
        item = email.message_from_bytes(bytes(item))
    if isinstance(item, email.message.Message):
        values = [value for name in RECIPIENT_HEADERS for value in item.get_all(name, [])]
    elif isinstance(item, dict):
        values = []
        evidence = item.get('recipient_evidence', [])
        if isinstance(evidence, list):
            values.extend(value for value in evidence if isinstance(value, str))
        for name in ('to', 'cc', 'delivered_to', 'x_original_to'):
            value = item.get(name)
            if isinstance(value, str):
                values.append(value)
        headers = item.get('recipient_headers', {})
        if isinstance(headers, dict):
            for name, value in headers.items():
                if name.lower() in {header.lower() for header in RECIPIENT_HEADERS}:
                    values.extend([value] if isinstance(value, str) else value if isinstance(value, list) else [])
        for header in item.get('internetMessageHeaders', []) or []:
            if isinstance(header, dict) and str(header.get('name', '')).lower() in {name.lower() for name in RECIPIENT_HEADERS}:
                values.append(header.get('value', ''))
    else:
        return set()
    return {address.strip().lower() for _, address in getaddresses([value for value in values if isinstance(value, str)]) if '@' in address}


def belongs_to(item, address):
    return address.strip().lower() in recipient_addresses(item)


def scan_isolated_mail(fetch_page, address, skip, top, *, deadline, detail=None, clock=time.monotonic, batch=50, limit=10000):
    """Filter before pagination. Incomplete scans contain only verified items."""
    matches, offset, seen = [], 0, set()
    while offset < limit:
        if clock() >= deadline:
            return {'success': False, 'emails': matches[skip:skip + top], 'scan_incomplete': True, 'error': '隐藏地址邮件扫描超时或未完成'}
        result = fetch_page(offset, batch)
        if clock() >= deadline or not result.get('success'):
            return {'success': False, 'emails': matches[skip:skip + top], 'scan_incomplete': True, 'error': '隐藏地址邮件扫描未完成'}
        rows = result.get('emails', [])
        for item in rows:
            key = (item.get('folder'), item.get('id'), item.get('id_mode'))
            if key in seen:
                continue
            seen.add(key)
            evidence = item
            if not belongs_to(evidence, address) and detail is not None:
                if clock() >= deadline:
                    break
                evidence = detail(item) or {}
            if belongs_to(evidence, address):
                matches.append(item)
        if len(matches) > skip + top or not result.get('has_more'):
            if clock() >= deadline:
                break
            return dict(result, emails=matches[skip:skip + top], has_more=len(matches) > skip + top, count=len(matches), isolated_address=address)
        if not rows:
            break
        offset += len(rows)
    return {'success': False, 'emails': matches[skip:skip + top], 'scan_incomplete': True, 'error': '隐藏地址邮件扫描达到上限或未完成'}
