from outlook_web import runtime


def test_resolve_secret_key_strips_environment_value(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "  abc123\n")

    assert runtime.resolve_secret_key() == "abc123"
