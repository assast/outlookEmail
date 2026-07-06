"""测试 OAuth 配置中包含 IMAP 权限（不依赖完整应用导入）"""
import ast
import pathlib


ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT_DIR / 'outlook_web' / 'segments' / '01_bootstrap.py'


def extract_oauth_scopes_from_source():
    """从源代码中提取 OAUTH_SCOPES 配置"""
    tree = ast.parse(BOOTSTRAP_PATH.read_text(encoding='utf-8'))

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'OAUTH_SCOPES':
                    if isinstance(node.value, ast.List):
                        scopes = []
                        for element in node.value.elts:
                            if isinstance(element, ast.Constant):
                                scopes.append(element.value)
                        return scopes
    return []


def test_oauth_scopes_contains_imap_permission():
    """验证 OAUTH_SCOPES 包含 IMAP 访问权限"""
    scopes = extract_oauth_scopes_from_source()
    imap_scope = "https://outlook.office.com/IMAP.AccessAsUser.All"

    assert imap_scope in scopes, \
        f"OAUTH_SCOPES 应该包含 IMAP 权限: {imap_scope}\n当前配置: {scopes}"
    print(f"[OK] IMAP 权限已配置: {imap_scope}")


def test_oauth_scopes_contains_offline_access():
    """验证 OAUTH_SCOPES 包含 offline_access（获取 RefreshToken 必需）"""
    scopes = extract_oauth_scopes_from_source()
    assert "offline_access" in scopes, \
        f"OAUTH_SCOPES 必须包含 offline_access 才能获取 RefreshToken\n当前配置: {scopes}"
    print("[OK] offline_access 已配置")


def test_oauth_scopes_contains_graph_mail_read():
    """验证 OAUTH_SCOPES 包含 Graph Mail.Read 权限"""
    scopes = extract_oauth_scopes_from_source()
    assert "https://graph.microsoft.com/Mail.Read" in scopes, \
        f"OAUTH_SCOPES 应该包含 Graph Mail.Read 权限\n当前配置: {scopes}"
    print("[OK] Graph Mail.Read 权限已配置")


def test_oauth_scopes_contains_graph_mail_readwrite():
    """验证 OAUTH_SCOPES 包含 Graph Mail.ReadWrite 权限"""
    scopes = extract_oauth_scopes_from_source()
    assert "https://graph.microsoft.com/Mail.ReadWrite" in scopes, \
        f"OAUTH_SCOPES 应该包含 Graph Mail.ReadWrite 权限\n当前配置: {scopes}"
    print("[OK] Graph Mail.ReadWrite 权限已配置")


def test_oauth_scopes_contains_graph_user_read():
    """验证 OAUTH_SCOPES 包含 Graph User.Read 权限"""
    scopes = extract_oauth_scopes_from_source()
    assert "https://graph.microsoft.com/User.Read" in scopes, \
        f"OAUTH_SCOPES 应该包含 Graph User.Read 权限\n当前配置: {scopes}"
    print("[OK] Graph User.Read 权限已配置")


def test_oauth_scopes_count():
    """验证 OAUTH_SCOPES 包含预期数量的权限"""
    scopes = extract_oauth_scopes_from_source()
    expected_count = 5  # offline_access + 3个Graph权限 + 1个IMAP权限
    assert len(scopes) == expected_count, \
        f"OAUTH_SCOPES 应该包含 {expected_count} 个权限，实际: {len(scopes)}\n当前配置: {scopes}"
    print(f"[OK] 权限数量正确: {len(scopes)} 个")


def test_oauth_scopes_has_no_duplicates():
    """验证 OAUTH_SCOPES 没有重复的权限"""
    scopes = extract_oauth_scopes_from_source()
    assert len(scopes) == len(set(scopes)), \
        f"OAUTH_SCOPES 不应包含重复权限: {scopes}"
    print("[OK] 无重复权限")


def test_oauth_scopes_all_valid():
    """验证所有权限都是有效的字符串"""
    scopes = extract_oauth_scopes_from_source()
    assert all(isinstance(scope, str) and scope.strip() for scope in scopes), \
        f"所有 scope 都应该是非空字符串: {scopes}"
    print("[OK] 所有权限格式有效")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("开始测试 OAuth IMAP Scope 配置")
    print("="*60 + "\n")

    tests = [
        test_oauth_scopes_contains_imap_permission,
        test_oauth_scopes_contains_offline_access,
        test_oauth_scopes_contains_graph_mail_read,
        test_oauth_scopes_contains_graph_mail_readwrite,
        test_oauth_scopes_contains_graph_user_read,
        test_oauth_scopes_count,
        test_oauth_scopes_has_no_duplicates,
        test_oauth_scopes_all_valid,
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
