"""测试 Web 后端的意图识别、序列化与导出。"""
import os

import pytest
from fastapi import HTTPException

import src.web.app as web_app
from src.diagnosis.engine import diagnose
from src.web.app import find_account


def test_find_account_by_name(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    assert find_account("为什么美妆旗舰店的ROI下降了") == "A001"


def test_find_account_by_id(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A002", "advertiser_name": "服饰旗舰店"}])
    assert find_account("A002 怎么了") == "A002"


def test_find_account_not_found(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    assert find_account("今天天气怎么样") is None


def test_serialize_result_has_structured_fields(demo_df, monkeypatch):
    monkeypatch.setattr(web_app, "generate_report", lambda r, df: "报告")
    r = diagnose(demo_df, "A001")
    s = web_app.serialize_result(r, demo_df)
    assert s["report"] == "报告"
    assert s["decision"] == "multiple"
    assert "evidence" in s and "scores" in s and "drilldowns" in s


def test_export_report_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "load_settings", lambda: {"export": {"dir": str(tmp_path)}})
    r = web_app.export_report(web_app.ExportIn(filename="test.md", content="# 报告"))
    assert r["ok"] is True
    assert (tmp_path / "test.md").read_text(encoding="utf-8") == "# 报告"


def test_export_report_sanitizes_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "load_settings", lambda: {"export": {"dir": str(tmp_path)}})
    r = web_app.export_report(web_app.ExportIn(filename="../evil:path", content="x"))
    assert os.path.dirname(r["path"]) == str(tmp_path)  # 不能逃逸出导出目录
    assert os.path.basename(r["path"]).endswith(".md")


def test_chat_api_records_keyword_miss_fallback(monkeypatch):
    """重构后 chat_api 对无关键词命中的问题应记录 keyword_miss 兜底。"""
    import pandas as pd
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda messages: "兜底回复")
    monkeypatch.setattr(web_app, "llm_route", lambda *a, **k: None)   # 不调真 LLM
    recorded = []
    monkeypatch.setattr(web_app, "record_fallback", lambda t: recorded.append(t))

    r = web_app.chat_api(web_app.ChatIn(message="帮我写一首诗"))
    assert r["type"] == "chat" and r["content"] == "兜底回复"
    assert recorded == ["keyword_miss"]


def test_chat_api_passes_session_and_user(monkeypatch):
    """chat_api 应把 session_id / user_id 透传给 trace（Langfuse 一等属性）。"""
    from contextlib import contextmanager
    import pandas as pd

    captured = {}

    class FakeTrace:
        def update(self, **k):
            pass

    @contextmanager
    def fake_trace(name, **kwargs):
        captured.update(kwargs)
        yield FakeTrace()

    monkeypatch.setattr(web_app, "trace", fake_trace)
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda messages: "ok")
    monkeypatch.setattr(web_app, "llm_route", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "record_fallback", lambda t: None)

    web_app.chat_api(web_app.ChatIn(message="帮我写诗", session_id="s123", user_id="u-abc"))
    assert captured["session_id"] == "s123"
    assert captured["user_id"] == "u-abc"


def test_chat_api_records_fallback_topic(monkeypatch):
    """兜底时除 fallback_type 外，还要记录归因话题（缺口信号）。"""
    import pandas as pd
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda m: "兜底回复")
    monkeypatch.setattr(web_app, "llm_route", lambda *a, **k: None)
    rec = {"fallbacks": [], "topics": []}
    monkeypatch.setattr(web_app, "record_fallback", lambda t: rec["fallbacks"].append(t))
    monkeypatch.setattr(web_app, "record_topic", lambda t: rec["topics"].append(t))

    web_app.chat_api(web_app.ChatIn(message="今天天气怎么样"))
    assert rec["fallbacks"] == ["keyword_miss"]
    assert rec["topics"] == ["天气/无关查询"]


def test_chat_api_llm_router_reroutes_to_diagnose(demo_df, monkeypatch):
    """关键词未命中时，LLM 二次路由把它改写成 diagnose → 真跑诊断。"""
    from contextlib import contextmanager
    captured = {}

    class FakeTrace:
        def update(self, **k):
            captured.update(k)

    @contextmanager
    def fake_trace(name, **kwargs):
        yield FakeTrace()

    monkeypatch.setattr(web_app, "trace", fake_trace)
    monkeypatch.setattr(web_app, "get_df", lambda: demo_df)
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店", "aliases": []}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "generate_report", lambda r, df: "报告")
    monkeypatch.setattr(web_app, "llm_route",
                        lambda msg, accounts: {"route": "diagnose", "account_id": "A001"})

    r = web_app.chat_api(web_app.ChatIn(message="这店最近转化不行"))
    assert r["type"] == "diagnose"
    assert captured["metadata"]["route_source"] == "llm"
    assert captured["metadata"]["llm_route"] == "diagnose"


def test_chat_api_llm_router_confirms_chat(monkeypatch):
    """LLM 二次路由也认为是闲聊 → 不改写，仍走兜底。"""
    from contextlib import contextmanager
    import pandas as pd

    captured = {}

    class FakeTrace:
        def update(self, **k):
            captured.update(k)

    @contextmanager
    def fake_trace(name, **kwargs):
        yield FakeTrace()

    monkeypatch.setattr(web_app, "trace", fake_trace)
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda m: "兜底回复")
    monkeypatch.setattr(web_app, "llm_route", lambda msg, accounts: {"route": "chat"})
    monkeypatch.setattr(web_app, "record_fallback", lambda t: None)
    monkeypatch.setattr(web_app, "record_topic", lambda t: None)

    r = web_app.chat_api(web_app.ChatIn(message="今天天气怎么样"))
    assert r["type"] == "chat"
    assert captured["metadata"]["route_source"] == "keyword"   # LLM 没改写
    assert captured["metadata"]["llm_route"] == "chat"


def test_chat_api_uses_llm_topic_over_keyword(monkeypatch):
    """LLM 二次路由已给出话题时，不再依赖关键词分类。"""
    import pandas as pd
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda m: "兜底回复")
    monkeypatch.setattr(web_app, "llm_route",
                        lambda msg, accounts: {"route": "chat", "topic": "选品推荐",
                                               "detail": "问该选什么品类"})
    rec = {"topics": []}
    monkeypatch.setattr(web_app, "record_fallback", lambda t: None)
    monkeypatch.setattr(web_app, "record_topic", lambda t: rec["topics"].append(t))

    web_app.chat_api(web_app.ChatIn(message="这个类目能做吗"))   # 关键词表归不了类
    assert rec["topics"] == ["选品推荐"]


def test_chat_api_records_new_topic(monkeypatch):
    """闭集未归上时，把 LLM 自拟的 new_topic 写进 metadata。"""
    from contextlib import contextmanager
    import pandas as pd

    captured = {}

    class FakeTrace:
        def update(self, **k):
            captured.update(k)

    @contextmanager
    def fake_trace(name, **kwargs):
        yield FakeTrace()

    monkeypatch.setattr(web_app, "trace", fake_trace)
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda m: "兜底回复")
    monkeypatch.setattr(web_app, "llm_route",
                        lambda msg, accounts: {"route": "chat", "topic": "未归类",
                                               "new_topic": "私域运营", "detail": "问私域转化"})
    monkeypatch.setattr(web_app, "record_fallback", lambda t: None)
    monkeypatch.setattr(web_app, "record_topic", lambda t: None)

    web_app.chat_api(web_app.ChatIn(message="怎么提升私域转化"))   # 关键词表也归不了
    assert captured["metadata"]["topic"] == "未归类"
    assert captured["metadata"]["new_topic"] == "私域运营"


def test_eval_signals_passthrough(monkeypatch):
    """访问控制由中间件负责，端点本身直接返回聚合结果。"""
    monkeypatch.setattr(web_app, "aggregate_signals", lambda: {"enabled": False, "total_traces": 0})
    assert web_app.eval_signals()["enabled"] is False


# ---------------------------------------------------------------- 登录 / 角色门禁
def _client():
    from fastapi.testclient import TestClient
    return TestClient(web_app.app)


def test_unauthenticated_blocked(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)
    monkeypatch.setattr(web_app.auth_mod, "current_user", lambda req: None)
    c = _client()
    assert c.get("/api/eval/signals").status_code == 401
    assert c.post("/api/chat", json={"message": "hi"}).status_code == 401
    r = c.get("/eval", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"


def test_developer_can_access_eval(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda req: {"username": "admin", "role": "developer"})
    monkeypatch.setattr(web_app, "aggregate_signals", lambda: {"enabled": True, "total_traces": 7})
    assert _client().get("/api/eval/signals").json()["total_traces"] == 7


def test_user_role_cannot_access_eval(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda req: {"username": "ops", "role": "user"})
    assert _client().get("/api/eval/signals").status_code == 403


def test_login_sets_cookie_with_default_admin(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)
    monkeypatch.setattr(web_app.auth_mod, "_auth_cfg", lambda: {})
    c = _client()
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200 and r.json()["role"] == "developer"
    assert web_app.auth_mod.COOKIE_NAME in r.cookies


def test_chat_api_uses_session_user_for_langfuse(monkeypatch):
    """user_id 取登录会话（服务端可信），不信任请求体。"""
    from contextlib import contextmanager
    import pandas as pd

    captured = {}

    class FakeTrace:
        def update(self, **k):
            pass

    @contextmanager
    def fake_trace(name, **kwargs):
        captured.update(kwargs)
        yield FakeTrace()

    monkeypatch.setattr(web_app, "trace", fake_trace)
    monkeypatch.setattr(web_app, "get_df", lambda: pd.DataFrame({"advertiser_id": ["A001"]}))
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    monkeypatch.setattr(web_app, "apply_llm_settings", lambda: None)
    monkeypatch.setattr(web_app, "available", lambda: True)
    monkeypatch.setattr(web_app, "chat", lambda m: "ok")
    monkeypatch.setattr(web_app, "llm_route", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "record_fallback", lambda t: None)
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda req: {"username": "alice", "role": "user"})

    class Req:
        pass

    web_app.chat_api(web_app.ChatIn(message="帮我写诗", session_id="s1"), request=Req())
    assert captured["user_id"] == "alice"
    assert captured["session_id"] == "s1"


def test_register_end_to_end(monkeypatch):
    import src.settings as settings
    store = {"auth": {"enabled": True, "users": []}}
    monkeypatch.setattr(settings, "load_settings", lambda: store)
    monkeypatch.setattr(settings, "save_settings", lambda s: None)
    c = _client()
    r = c.post("/api/auth/register", json={"username": "ops9", "password": "secret9"})
    assert r.status_code == 200
    assert r.json() == {"username": "ops9", "role": "user"}
    assert web_app.auth_mod.COOKIE_NAME in r.cookies


def test_register_error_mapping(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)

    def boom(u, p, role="user"):
        raise ValueError("用户名已存在")

    monkeypatch.setattr(web_app.auth_mod, "add_user", boom)
    r = _client().post("/api/auth/register", json={"username": "x", "password": "secret1"})
    assert r.status_code == 409


# ---------------------------------------------------------------- 账号管理

def test_sessions_scoped_to_current_user(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "user1", "role": "user"})
    monkeypatch.setattr(web_app, "sessions_for", lambda u: [{"id": "u1", "user": u}])

    class Req:
        pass

    assert web_app.get_sessions(request=Req())["sessions"] == [{"id": "u1", "user": "user1"}]


def test_put_sessions_scoped(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "user1", "role": "user"})
    captured = {}
    monkeypatch.setattr(web_app, "replace_user_sessions",
                        lambda u, s: captured.update(user=u) or s)

    class Req:
        pass

    web_app.put_sessions(web_app.SessionsIn(sessions=[{"id": "u2"}]), request=Req())
    assert captured["user"] == "user1"


def test_account_me(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "bob", "role": "user"})
    monkeypatch.setattr(web_app.auth_mod, "public_profile",
                        lambda u: {"username": u, "role": "user", "email": "a@b.com", "phone": ""})
    assert web_app.account_me(request=None)["email"] == "a@b.com"


def test_account_password_error_mapping(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "bob", "role": "user"})

    def boom(u, o, n):
        raise ValueError("当前密码不正确")

    monkeypatch.setattr(web_app.auth_mod, "update_password", boom)
    with pytest.raises(HTTPException) as ei:
        web_app.account_password(web_app.PasswordIn(old_password="x", new_password="yyyyyy"), request=None)
    assert ei.value.status_code == 400


def test_account_username_reissues_cookie(monkeypatch):
    from fastapi import Response

    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "bob", "role": "user"})
    monkeypatch.setattr(web_app.auth_mod, "update_username",
                        lambda o, n: {"username": n, "role": "user"})
    resp = Response()
    out = web_app.account_username(web_app.UsernameIn(new_username="bob2"), request=None, response=resp)
    assert out["username"] == "bob2"
    assert web_app.auth_mod.COOKIE_NAME in resp.headers.get("set-cookie", "")


def test_account_profile(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "current_user",
                        lambda r: {"username": "bob", "role": "user"})
    monkeypatch.setattr(web_app.auth_mod, "update_profile",
                        lambda u, email=None, phone=None: {"email": email or "", "phone": phone or ""})
    out = web_app.account_profile(web_app.ProfileIn(email="a@b.com"), request=None)
    assert out["email"] == "a@b.com"


def test_account_flow_end_to_end(monkeypatch):
    """注册 → 改密码 → 改用户名 → 绑邮箱/手机 → 用新密码登录。"""
    import src.settings as settings
    store = {"auth": {"enabled": True, "users": []}}
    monkeypatch.setattr(settings, "load_settings", lambda: store)
    monkeypatch.setattr(settings, "save_settings", lambda s: None)

    c = _client()
    assert c.post("/api/auth/register",
                  json={"username": "ops9", "password": "secret9"}).status_code == 200

    assert c.post("/api/account/password",
                  json={"old_password": "secret9", "new_password": "newpass9"}).status_code == 200
    r = c.post("/api/account/username", json={"new_username": "ops10"})
    assert r.status_code == 200 and r.json()["username"] == "ops10"
    assert c.post("/api/account/profile",
                  json={"email": "a@b.com", "phone": "13812345678"}).status_code == 200

    me = c.get("/api/account/me").json()
    assert me["username"] == "ops10" and me["email"] == "a@b.com"
    assert me["phone"] == "13812345678"

    fresh = _client()
    assert fresh.post("/api/auth/login",
                      json={"username": "ops10", "password": "newpass9"}).status_code == 200
    assert fresh.post("/api/auth/login",
                      json={"username": "ops10", "password": "secret9"}).status_code == 401


def test_login_page_served(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: False)
    r = _client().get("/login")
    assert r.status_code == 200 and "投放诊断" in r.text


def test_login_rejects_bad_password(monkeypatch):
    monkeypatch.setattr(web_app.auth_mod, "auth_enabled", lambda: True)
    monkeypatch.setattr(web_app.auth_mod, "_auth_cfg", lambda: {})
    r = _client().post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
