"""测试 src/sessions_store.py：对话会话持久化。"""
import src.sessions_store as store


def test_save_and_load_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "sessions.json")
    store.save_sessions([{"id": "s1", "title": "测试会话", "messages": []}])
    assert store.load_sessions() == [{"id": "s1", "title": "测试会话", "messages": []}]


def test_load_sessions_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "nope.json")
    assert store.load_sessions() == []


def test_sessions_are_scoped_by_user(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "sessions.json")
    store.save_sessions([
        {"id": "a1", "user": "admin", "messages": []},
        {"id": "u1", "user": "user1", "messages": []},
        {"id": "legacy", "messages": []},          # 无 user → 视为 admin
    ])
    assert [s["id"] for s in store.sessions_for("admin")] == ["a1", "legacy"]
    assert [s["id"] for s in store.sessions_for("user1")] == ["u1"]


def test_replace_user_sessions_keeps_others(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "sessions.json")
    store.save_sessions([
        {"id": "a1", "user": "admin", "messages": []},
        {"id": "u1", "user": "user1", "messages": []},
    ])
    # user1 保存自己的（删 u1、新增 u2）——admin 的 a1 必须完好
    store.replace_user_sessions("user1", [{"id": "u2", "messages": []}])
    assert {s["id"] for s in store.load_sessions()} == {"a1", "u2"}
    assert store.sessions_for("user1")[0]["user"] == "user1"   # 已打上归属


def test_legacy_sessions_claimed_by_admin_on_write(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "sessions.json")
    store.save_sessions([{"id": "old", "messages": []}])
    store.replace_user_sessions("admin", store.sessions_for("admin"))
    assert store.load_sessions()[0]["user"] == "admin"
