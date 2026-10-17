"""测试 src/auth：密码哈希、会话签名、鉴权。"""
import pytest

from src import auth


def test_hash_and_verify_password():
    h = auth.hash_password("secret", salt=b"0" * 16, iters=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("secret", h) is True
    assert auth.verify_password("wrong", h) is False
    assert auth.verify_password("secret", "garbage") is False
    assert auth.verify_password("secret", "md5$x$y$z") is False


def test_session_roundtrip():
    tok = auth.make_session("alice", "developer", "sec", hours=1)
    assert auth.parse_session(tok, "sec") == {"username": "alice", "role": "developer"}


def test_session_rejects_tampering_and_bad_secret():
    tok = auth.make_session("alice", "developer", "sec", hours=1)
    assert auth.parse_session(tok, "other-secret") is None
    assert auth.parse_session(tok + "x", "sec") is None
    assert auth.parse_session("not-a-token", "sec") is None
    assert auth.parse_session("", "sec") is None


def test_session_expired():
    raw = b'{"u":"a","r":"user","exp":1}'
    sig = auth.hmac.new(b"sec", raw, auth.hashlib.sha256).digest()
    expired = auth._b64e(raw) + "." + auth._b64e(sig)
    assert auth.parse_session(expired, "sec") is None


def test_authenticate_default_admin(monkeypatch):
    monkeypatch.setattr(auth, "_auth_cfg", lambda: {})
    assert auth.authenticate("admin", "admin123") == {"username": "admin", "role": "developer"}
    assert auth.authenticate("admin", "wrong") is None
    assert auth.authenticate("nobody", "x") is None


def test_authenticate_custom_users(monkeypatch):
    users = [{"username": "ops", "password_hash": auth.hash_password("p", iters=1000),
              "role": "user"}]
    monkeypatch.setattr(auth, "_auth_cfg", lambda: {"users": users})
    assert auth.authenticate("ops", "p") == {"username": "ops", "role": "user"}


def test_valid_username():
    assert auth.valid_username("ops_01") and auth.valid_username("abc")
    assert not auth.valid_username("ab")          # 太短
    assert not auth.valid_username("中文名")       # 非 ASCII
    assert not auth.valid_username("a b")          # 空格
    assert not auth.valid_username("x" * 21)       # 太长


def test_add_user_keeps_default_admin(monkeypatch):
    import src.settings as settings
    store = {"auth": {"users": []}}
    monkeypatch.setattr(settings, "load_settings", lambda: store)
    monkeypatch.setattr(settings, "save_settings", lambda s: None)

    assert auth.add_user("ops", "secret1", role="user") == {"username": "ops", "role": "user"}
    names = [u["username"] for u in store["auth"]["users"]]
    assert "admin" in names and "ops" in names          # 默认开发者没被顶掉
    assert next(u for u in store["auth"]["users"] if u["username"] == "ops")["role"] == "user"


def test_add_user_rejects_duplicate_and_bad_input(monkeypatch):
    import src.settings as settings
    store = {"auth": {"users": [{"username": "ops", "password_hash": "x", "role": "user"}]}}
    monkeypatch.setattr(settings, "load_settings", lambda: store)
    monkeypatch.setattr(settings, "save_settings", lambda s: None)
    with pytest.raises(ValueError):
        auth.add_user("ops", "secret1")
    with pytest.raises(ValueError):
        auth.add_user("中文", "secret1")
    with pytest.raises(ValueError):
        auth.add_user("newbie", "123")


def _patch_settings(monkeypatch, users):
    import src.settings as settings
    store = {"auth": {"enabled": True, "users": users}}
    monkeypatch.setattr(settings, "load_settings", lambda: store)
    monkeypatch.setattr(settings, "save_settings", lambda s: None)
    return store


def test_update_password(monkeypatch):
    store = _patch_settings(monkeypatch, [
        {"username": "ops", "password_hash": auth.hash_password("old123", iters=1000), "role": "user"}])
    with pytest.raises(ValueError):
        auth.update_password("ops", "wrong", "new123")   # 旧密码错
    with pytest.raises(ValueError):
        auth.update_password("ops", "old123", "123")      # 新密码太短
    auth.update_password("ops", "old123", "new123")
    assert auth.verify_password("new123", store["auth"]["users"][0]["password_hash"])


def test_update_username(monkeypatch):
    store = _patch_settings(monkeypatch, [
        {"username": "admin", "password_hash": "x", "role": "developer"},
        {"username": "ops", "password_hash": "y", "role": "user"}])
    with pytest.raises(ValueError):
        auth.update_username("ops", "admin")     # 重名
    with pytest.raises(ValueError):
        auth.update_username("ops", "中文")       # 非 ASCII
    assert auth.update_username("ops", "ops2") == {"username": "ops2", "role": "user"}
    assert store["auth"]["users"][1]["username"] == "ops2"


def test_update_profile(monkeypatch):
    store = _patch_settings(monkeypatch, [
        {"username": "ops", "password_hash": "x", "role": "user"}])
    auth.update_profile("ops", email="a@b.com", phone="13812345678")
    assert store["auth"]["users"][0]["email"] == "a@b.com"
    assert store["auth"]["users"][0]["phone"] == "13812345678"
    with pytest.raises(ValueError):
        auth.update_profile("ops", email="bad-email")
    with pytest.raises(ValueError):
        auth.update_profile("ops", phone="12345")
    auth.update_profile("ops", email="")          # 解绑
    assert store["auth"]["users"][0]["email"] == ""


def test_public_profile(monkeypatch):
    _patch_settings(monkeypatch, [
        {"username": "ops", "password_hash": "x", "role": "user",
         "email": "a@b.com", "phone": "13812345678"}])
    assert auth.public_profile("ops") == {
        "username": "ops", "role": "user", "email": "a@b.com", "phone": "13812345678"}
    assert auth.public_profile("nope") is None


def test_current_user_from_request():
    tok = auth.make_session("bob", "user", "sec", hours=1)
    monkeypatch_secret = auth.session_secret
    auth.session_secret = lambda: "sec"  # type: ignore[assignment]
    try:
        class Req:
            cookies = {auth.COOKIE_NAME: tok}
        assert auth.current_user(Req()) == {"username": "bob", "role": "user"}
        assert auth.current_user(None) is None
    finally:
        auth.session_secret = monkeypatch_secret  # type: ignore[assignment]
