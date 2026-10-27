import email

from outlook_web.icloud_mail import belongs_to, recipient_addresses, scan_isolated_mail


def test_exact_recipient_evidence_in_multiple_headers_and_shared_recipients():
    raw = b'To: Display <a@icloud.com>, b@icloud.com\r\nCc: c@icloud.com\r\nDelivered-To: d@icloud.com\r\nX-Original-To: e@icloud.com\r\n\r\nbody includes z@icloud.com'
    assert recipient_addresses(raw) == {'a@icloud.com', 'b@icloud.com', 'c@icloud.com', 'd@icloud.com', 'e@icloud.com'}
    assert belongs_to(raw, 'A@ICLOUD.COM') and belongs_to(raw, 'b@icloud.com')
    assert not belongs_to(raw, 'z@icloud.com')
    assert not belongs_to({'to': 'prefixa@icloud.com', 'body': 'a@icloud.com', 'subject': 'a@icloud.com'}, 'a@icloud.com')
    assert not belongs_to({'body': 'a@icloud.com'}, 'a@icloud.com')


def test_scans_past_non_matching_first_pages_and_paginates_matches():
    rows = [{'id': str(i), 'to': 'b@icloud.com' if i < 120 else 'a@icloud.com'} for i in range(130)]
    calls = []
    def fetch(offset, batch):
        calls.append(offset)
        return {'success': True, 'emails': rows[offset:offset + batch], 'has_more': offset + batch < len(rows)}
    result = scan_isolated_mail(fetch, 'a@icloud.com', 2, 3, deadline=10, clock=lambda: 0)
    assert result['success'] and [item['id'] for item in result['emails']] == ['122', '123', '124']
    assert calls == [0, 50, 100]


def test_missing_cached_evidence_never_bypasses_detail_check_or_timeout():
    result = scan_isolated_mail(lambda *_: {'success': True, 'emails': [{'id': 'b'}], 'has_more': False},
        'a@icloud.com', 0, 10, deadline=10, clock=lambda: 0, detail=lambda _: {'to': 'b@icloud.com', 'body': 'private'})
    assert result['success'] and result['emails'] == []
    result = scan_isolated_mail(lambda *_: {'success': True, 'emails': [], 'has_more': True},
        'a@icloud.com', 0, 10, deadline=0, clock=lambda: 0)
    assert not result['success'] and result['scan_incomplete']
