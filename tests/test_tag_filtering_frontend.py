import json
import subprocess
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '01-core.js'
GROUPS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '02-groups.js'
TAGS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '09-tags.js'
TEMP_EMAILS_JS_PATH = ROOT_DIR / 'static' / 'js' / 'index' / '03-temp-emails.js'


def _extract_function(source: str, function_name: str) -> str:
    signature = f'function {function_name}('
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


def _run_node(script: str):
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


class TagFilteringFrontendTests(unittest.TestCase):
    def test_shared_tag_matcher_supports_include_and_exclude(self):
        source = CORE_JS_PATH.read_text(encoding='utf-8')
        matcher_source = '\n'.join([
            _extract_function(source, 'normalizeTagFilterSelectionValue'),
            _extract_function(source, 'hasActiveTagFilters'),
            _extract_function(source, 'matchesSelectedTagFilters'),
        ])
        script = f"""
let selectedTagFilters = new Set();
let excludedTagFilters = new Set();
{matcher_source}
const cases = {{
    includeAny: (() => {{
        selectedTagFilters = new Set([1, 2]);
        excludedTagFilters = new Set();
        return [
            matchesSelectedTagFilters([{{ id: 1 }}]),
            matchesSelectedTagFilters([{{ id: 2 }}]),
            matchesSelectedTagFilters([{{ id: 1 }}, {{ id: 2 }}]),
            matchesSelectedTagFilters([{{ id: 3 }}]),
            matchesSelectedTagFilters([]),
        ];
    }})(),
    excludeOnly: (() => {{
        selectedTagFilters = new Set();
        excludedTagFilters = new Set([2, 3]);
        return [
            matchesSelectedTagFilters([{{ id: 1 }}]),
            matchesSelectedTagFilters([{{ id: 2 }}]),
            matchesSelectedTagFilters([{{ id: 3 }}]),
            matchesSelectedTagFilters([{{ id: 2 }}, {{ id: 3 }}]),
            matchesSelectedTagFilters([]),
        ];
    }})(),
    includeAndExclude: (() => {{
        selectedTagFilters = new Set([1, 2]);
        excludedTagFilters = new Set([3, 4]);
        return [
            matchesSelectedTagFilters([{{ id: 1 }}]),
            matchesSelectedTagFilters([{{ id: 2 }}, {{ id: 3 }}]),
            matchesSelectedTagFilters([{{ id: 1 }}, {{ id: 4 }}]),
            matchesSelectedTagFilters([{{ id: 3 }}]),
            matchesSelectedTagFilters([]),
        ];
    }})(),
    activeExcludeOnly: (() => {{
        selectedTagFilters = new Set();
        excludedTagFilters = new Set([2]);
        return hasActiveTagFilters();
    }})(),
    legacyUntaggedValue: normalizeTagFilterSelectionValue('__untagged__'),
}};
console.log(JSON.stringify(cases));
"""
        values = _run_node(script)

        self.assertEqual(values['includeAny'], [True, True, True, False, False])
        self.assertEqual(values['excludeOnly'], [True, False, False, False, True])
        self.assertEqual(values['includeAndExclude'], [True, False, False, False, False])
        self.assertTrue(values['activeExcludeOnly'])
        self.assertIsNone(values['legacyUntaggedValue'])

    def test_tag_filter_state_selection_is_mutually_exclusive(self):
        core_source = CORE_JS_PATH.read_text(encoding='utf-8')
        groups_source = GROUPS_JS_PATH.read_text(encoding='utf-8')
        function_source = '\n'.join([
            _extract_function(core_source, 'normalizeTagFilterSelectionValue'),
            _extract_function(groups_source, 'setAccountTagFilterSelection'),
        ])
        script = f"""
let selectedTagFilters = new Set([1]);
let excludedTagFilters = new Set();
let changeCount = 0;
function applyAccountTagFilterChange() {{ changeCount += 1; }}
{function_source}
setAccountTagFilterSelection(1, 'exclude');
const excluded = {{ include: Array.from(selectedTagFilters), exclude: Array.from(excludedTagFilters) }};
setAccountTagFilterSelection(1, 'include');
const included = {{ include: Array.from(selectedTagFilters), exclude: Array.from(excludedTagFilters) }};
console.log(JSON.stringify({{ excluded, included, changeCount }}));
"""
        values = _run_node(script)

        self.assertEqual(values['excluded'], {'include': [], 'exclude': [1]})
        self.assertEqual(values['included'], {'include': [1], 'exclude': []})
        self.assertEqual(values['changeCount'], 2)

    def test_preferences_clear_legacy_untagged_values_and_store_excludes_separately(self):
        core_source = CORE_JS_PATH.read_text(encoding='utf-8')
        groups_source = GROUPS_JS_PATH.read_text(encoding='utf-8')
        function_source = '\n'.join([
            _extract_function(core_source, 'normalizeTagFilterSelectionValue'),
            _extract_function(groups_source, 'loadStoredAccountTagFilterValues'),
            _extract_function(groups_source, 'saveAccountTagFilterPreferenceValues'),
            _extract_function(groups_source, 'loadAccountTagFilterPreference'),
            _extract_function(groups_source, 'saveAccountTagFilterPreference'),
            _extract_function(groups_source, 'loadAccountTagExcludeFilterPreference'),
            _extract_function(groups_source, 'saveAccountTagExcludeFilterPreference'),
            _extract_function(groups_source, 'getAccountTagFilterParams'),
            _extract_function(groups_source, 'hasAccountServerSideFilters'),
            _extract_function(groups_source, 'appendAccountListParams'),
        ])
        script = f"""
const ACCOUNT_TAG_FILTER_STORAGE_KEY = 'outlook_account_tag_filters';
const ACCOUNT_TAG_EXCLUDE_FILTER_STORAGE_KEY = 'outlook_account_tag_exclude_filters';
const storage = new Map([
    [ACCOUNT_TAG_FILTER_STORAGE_KEY, JSON.stringify([1, '__untagged__'])],
    [ACCOUNT_TAG_EXCLUDE_FILTER_STORAGE_KEY, JSON.stringify([2, '__untagged__'])],
]);
const localStorage = {{
    getItem(key) {{ return storage.has(key) ? storage.get(key) : null; }},
    setItem(key, value) {{ storage.set(key, String(value)); }},
}};
let selectedTagFilters = new Set();
let excludedTagFilters = new Set();
function getAccountPageSize() {{ return 200; }}
let currentSortBy = 'email';
let currentSortOrder = 'asc';
{function_source}
selectedTagFilters = loadAccountTagFilterPreference();
excludedTagFilters = loadAccountTagExcludeFilterPreference();
const legacy = {{
    include: Array.from(selectedTagFilters),
    exclude: Array.from(excludedTagFilters),
}};
const storedAfterLoad = {{
    include: JSON.parse(storage.get(ACCOUNT_TAG_FILTER_STORAGE_KEY)),
    exclude: JSON.parse(storage.get(ACCOUNT_TAG_EXCLUDE_FILTER_STORAGE_KEY)),
}};
selectedTagFilters = new Set([1, 2, '__untagged__']);
excludedTagFilters = new Set([2, 3, '__untagged__']);
saveAccountTagFilterPreference();
saveAccountTagExcludeFilterPreference();
const filters = getAccountTagFilterParams();
const params = appendAccountListParams(new URLSearchParams());
console.log(JSON.stringify({{
    legacy,
    storedAfterLoad,
    storedInclude: JSON.parse(storage.get(ACCOUNT_TAG_FILTER_STORAGE_KEY)),
    storedExclude: JSON.parse(storage.get(ACCOUNT_TAG_EXCLUDE_FILTER_STORAGE_KEY)),
    filters,
    hasServerFilters: hasAccountServerSideFilters(),
    params: Array.from(params.entries()),
}}));
"""
        values = _run_node(script)

        self.assertEqual(values['legacy'], {'include': [1], 'exclude': [2]})
        self.assertEqual(values['storedAfterLoad'], {'include': [1], 'exclude': [2]})
        self.assertEqual(values['storedInclude'], [1, 2])
        self.assertEqual(values['storedExclude'], [2, 3])
        self.assertEqual(values['filters'], {
            'tagIds': [1, 2],
            'excludeTagIds': [2, 3],
        })
        self.assertTrue(values['hasServerFilters'])
        self.assertIn(['tag_ids', '1,2'], values['params'])
        self.assertIn(['exclude_tag_ids', '2'], values['params'])
        self.assertIn(['exclude_tag_ids', '3'], values['params'])
        self.assertNotIn(['include_untagged', '1'], values['params'])

    def test_tag_loading_prunes_both_groups_with_include_precedence(self):
        source = TAGS_JS_PATH.read_text(encoding='utf-8')
        prune_source = _extract_function(source, 'pruneAccountTagFilterSelections')
        script = f"""
let allTags = [{{ id: 1 }}, {{ id: 2 }}];
let selectedTagFilters = new Set([1, 99, '__untagged__']);
let excludedTagFilters = new Set([1, 2, 99, '__untagged__']);
function normalizeTagFilterSelectionValue(value) {{
    const normalized = Number.parseInt(String(value ?? '').trim(), 10);
    return Number.isFinite(normalized) ? normalized : null;
}}
{prune_source}
pruneAccountTagFilterSelections();
console.log(JSON.stringify({{
    include: Array.from(selectedTagFilters),
    exclude: Array.from(excludedTagFilters),
}}));
"""
        values = _run_node(script)

        self.assertEqual(values, {'include': [1], 'exclude': [2]})

    def test_account_filter_ui_and_temp_email_renderer_use_only_real_tag_states(self):
        groups_source = GROUPS_JS_PATH.read_text(encoding='utf-8')
        tags_source = TAGS_JS_PATH.read_text(encoding='utf-8')
        temp_emails_source = TEMP_EMAILS_JS_PATH.read_text(encoding='utf-8')

        self.assertIn('hasActiveTagFilters()', groups_source)
        self.assertIn('hasActiveTagFilters()', temp_emails_source)
        self.assertIn('matchesSelectedTagFilters(email.tags)', temp_emails_source)
        self.assertIn('function buildAccountTagFilterOptionsHtml()', tags_source)
        self.assertIn('>有<', tags_source)
        self.assertIn('>无<', tags_source)
        self.assertIn('data-tag-name=', tags_source)
        self.assertIn('filterTagOptions(tagFilterKeyword);', tags_source)
        self.assertNotIn('UNTAGGED_TAG_FILTER', tags_source)
        self.assertNotIn('无标签</span>', tags_source)
        self.assertNotIn('include_untagged', groups_source)


if __name__ == '__main__':
    unittest.main()
