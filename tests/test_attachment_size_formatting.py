import json
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
EMAILS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '05-emails.js'


def _extract_function(source, function_name):
    signature = f'function {function_name}'
    start = source.index(signature)
    body_start = source.index('{', start)
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f'{function_name} body was not closed')


def _format_attachment_sizes(*sizes):
    source = EMAILS_JS_PATH.read_text(encoding='utf-8')
    function_source = _extract_function(source, 'formatAttachmentSize')
    script = f"""
{function_source}
const sizes = {json.dumps(list(sizes))};
console.log(JSON.stringify(sizes.map(size => formatAttachmentSize(size))));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def test_attachment_size_drops_trailing_decimal_zero_for_integer_kb():
    assert _format_attachment_sizes(1024)[0] == '1 KB'


def test_attachment_size_keeps_single_decimal_for_non_integer_kb():
    assert _format_attachment_sizes(1536, 1572864) == ['1.5 KB', '1.5 MB']
