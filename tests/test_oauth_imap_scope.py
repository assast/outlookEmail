"""测试手动 OAuth 配置只请求 IMAP 单资源权限（不依赖完整应用导入）"""
import ast
import pathlib


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT_DIR / 'outlook_web' / 'segments' / '01_bootstrap.py'
HELPERS_PATH = ROOT_DIR / 'outlook_web' / 'segments' / '03_mail_helpers.py'


def extract_assignment_value(path, name):
    """从源代码中提取常量赋值。"""
    tree = ast.parse(path.read_text(encoding='utf-8'))

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.List):
                        scopes = []
                        for element in node.value.elts:
                            if isinstance(element, ast.Constant):
                                scopes.append(element.value)
                        return scopes
                    if isinstance(node.value, ast.Constant):
                        return node.value.value
    return None


def extract_oauth_scopes_from_source():
    """从源代码中提取手动 OAuth scope 配置。"""
    return extract_assignment_value(BOOTSTRAP_PATH, 'OAUTH_SCOPES') or []


def extract_graph_oauth_scopes_from_source():
    """从源代码中提取 Graph 专用 scope 配置。"""
    return extract_assignment_value(BOOTSTRAP_PATH, 'OAUTH_GRAPH_SCOPES') or []


def scope_resource(scope):
    if scope == 'offline_access':
        return ''
    if scope.startswith('https://graph.microsoft.com/'):
        return 'https://graph.microsoft.com'
    if scope.startswith('https://outlook.office.com/'):
        return 'https://outlook.office.com'
    return scope.rsplit('/', 1)[0] if '/' in scope else scope


def test_manual_oauth_scopes_are_imap_only():
    """手动授权不能混用 Graph 和 Outlook IMAP 两个资源，否则会触发 AADSTS70011。"""
    scopes = extract_oauth_scopes_from_source()
    imap_scope = "https://outlook.office.com/IMAP.AccessAsUser.All"

    assert scopes == ["offline_access", imap_scope], \
        f"手动 OAuth 只应请求 Outlook IMAP 单资源权限，当前配置: {scopes}"


def test_oauth_scopes_contains_offline_access():
    """验证 OAUTH_SCOPES 包含 offline_access（获取 RefreshToken 必需）"""
    scopes = extract_oauth_scopes_from_source()
    assert "offline_access" in scopes, \
        f"OAUTH_SCOPES 必须包含 offline_access 才能获取 RefreshToken\n当前配置: {scopes}"


def test_oauth_scopes_count():
    """验证 OAUTH_SCOPES 包含预期数量的权限"""
    scopes = extract_oauth_scopes_from_source()
    expected_count = 2  # offline_access + IMAP 权限
    assert len(scopes) == expected_count, \
        f"OAUTH_SCOPES 应该包含 {expected_count} 个权限，实际: {len(scopes)}\n当前配置: {scopes}"


def test_oauth_scopes_has_no_duplicates():
    """验证 OAUTH_SCOPES 没有重复的权限"""
    scopes = extract_oauth_scopes_from_source()
    assert len(scopes) == len(set(scopes)), \
        f"OAUTH_SCOPES 不应包含重复权限: {scopes}"


def test_oauth_scopes_all_valid():
    """验证所有权限都是有效的字符串"""
    scopes = extract_oauth_scopes_from_source()
    assert all(isinstance(scope, str) and scope.strip() for scope in scopes), \
        f"所有 scope 都应该是非空字符串: {scopes}"


def test_manual_oauth_scopes_do_not_mix_resource_hosts():
    """OAuth v2 单次授权请求的 scope 只能包含一个资源主机。"""
    scopes = extract_oauth_scopes_from_source()
    resource_hosts = {scope_resource(scope) for scope in scopes if scope_resource(scope)}

    assert resource_hosts == {'https://outlook.office.com'}, \
        f"手动 OAuth scope 不能混用多个资源: {scopes}"


def test_manual_oauth_scopes_match_imap_token_scope():
    """授权码换 token 和 refresh token 请求使用相同 IMAP 权限集合。"""
    scopes = extract_oauth_scopes_from_source()
    imap_token_scope = extract_assignment_value(HELPERS_PATH, 'IMAP_TOKEN_SCOPE')

    assert set(scopes) == set(str(imap_token_scope).split()), \
        f"手动 OAuth scope 应与 IMAP_TOKEN_SCOPE 一致: {scopes} vs {imap_token_scope}"


def test_graph_scopes_are_kept_separate_from_manual_oauth_scopes():
    """Graph 权限仍保留给 Graph token fallback，但不进入手动授权链接。"""
    graph_scopes = extract_graph_oauth_scopes_from_source()
    manual_scopes = extract_oauth_scopes_from_source()

    assert "https://graph.microsoft.com/Mail.Read" in graph_scopes
    assert "https://graph.microsoft.com/Mail.ReadWrite" in graph_scopes
    assert "https://graph.microsoft.com/User.Read" in graph_scopes
    assert all(scope not in manual_scopes for scope in graph_scopes)


if __name__ == '__main__':
    print("\n" + "="*60)
    print("开始测试 OAuth IMAP Scope 配置")
    print("="*60 + "\n")

    tests = [
        test_manual_oauth_scopes_are_imap_only,
        test_oauth_scopes_contains_offline_access,
        test_oauth_scopes_count,
        test_oauth_scopes_has_no_duplicates,
        test_oauth_scopes_all_valid,
        test_manual_oauth_scopes_do_not_mix_resource_hosts,
        test_manual_oauth_scopes_match_imap_token_scope,
        test_graph_scopes_are_kept_separate_from_manual_oauth_scopes,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print("\n" + "="*60)
    if failed == 0:
        print("[SUCCESS] 所有测试通过！")

        # 打印当前配置
        scopes = extract_oauth_scopes_from_source()
        print("\n当前 OAUTH_SCOPES 配置:")
        for i, scope in enumerate(scopes, 1):
            print(f"  {i}. {scope}")
    else:
        print(f"[FAIL] {failed} 个测试失败")
    print("="*60 + "\n")
