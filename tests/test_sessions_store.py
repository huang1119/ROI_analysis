"""测试 src/sessions_store.py：对话会话持久化。"""
import src.sessions_store as store


def test_save_and_load_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "sessions.json")
    store.save_sessions([{"id": "s1", "title": "测试会话", "messages": []}])
    assert store.load_sessions() == [{"id": "s1", "title": "测试会话", "messages": []}]


def test_load_sessions_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_PATH", tmp_path / "nope.json")
    assert store.load_sessions() == []
