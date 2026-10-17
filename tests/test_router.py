"""测试 src/llm/router.py：路由词表（同义说法）+ 账户别名/模糊匹配。"""
from src.llm.router import find_account, llm_route, route_message

ACCOUNTS = [
    {"advertiser_id": "A001", "advertiser_name": "美妆旗舰店", "aliases": ["美妆店"]},
    {"advertiser_id": "A002", "advertiser_name": "服饰旗舰店", "aliases": ["服饰店"]},
]


def _route(q, llm=True):
    return route_message(q, accounts=ACCOUNTS, llm_available=llm)


# ---------------------------------------------------------------- 词表
def test_exact_keywords():
    assert _route("扫描所有账户")["route"] == "scan"
    assert _route("有哪些账户")["route"] == "list"
    d = _route("A001 的ROI为什么掉了")
    assert d["route"] == "diagnose" and d["account_id"] == "A001"


def test_scan_synonyms():
    for q in ["扫一遍全部广告主", "帮我全量体检一下", "看看所有店铺的情况"]:
        assert _route(q)["route"] == "scan", q


def test_list_synonyms():
    assert _route("我有哪些账号")["route"] == "list"


def test_unmatched_falls_to_chat():
    d = _route("今天天气怎么样", llm=True)
    assert d == {"route": "chat", "fallback_type": "keyword_miss"}
    assert _route("今天天气怎么样", llm=False)["fallback_type"] == "no_llm_available"


# ---------------------------------------------------------------- 账户匹配
def test_account_alias_hits_diagnose():
    d = _route("美妆店最近怎么样")
    assert d["route"] == "diagnose" and d["account_id"] == "A001"


def test_account_fuzzy_tolerates_typo():
    assert find_account("美状旗舰店的ROI怎么掉了", ACCOUNTS) == "A001"


def test_account_ambiguous_returns_none():
    # 只提「旗舰店」→ 两个账户都像，不猜（避免诊断错账户）
    assert find_account("旗舰店最近怎么样", ACCOUNTS) is None


def test_account_unrelated_returns_none():
    assert find_account("今天天气怎么样", ACCOUNTS) is None


# ---------------------------------------------------------------- LLM 二次路由
def _patch_llm(monkeypatch, reply):
    import src.llm.client as client_mod
    monkeypatch.setattr(client_mod, "available", lambda: True)
    monkeypatch.setattr(client_mod, "chat", lambda messages, **k: reply)


def test_llm_route_parses_json(monkeypatch):
    _patch_llm(monkeypatch, '{"route":"diagnose","account_id":"A001"}')
    assert llm_route("这店转化不行", ACCOUNTS) == {"route": "diagnose", "account_id": "A001"}


def test_llm_route_parses_fenced_json(monkeypatch):
    _patch_llm(monkeypatch, '```json\n{"route":"scan"}\n```')
    assert llm_route("看看全部", ACCOUNTS) == {"route": "scan"}


def test_llm_route_rejects_unknown_account(monkeypatch):
    _patch_llm(monkeypatch, '{"route":"diagnose","account_id":"A999"}')
    assert llm_route("x", ACCOUNTS) is None


def test_llm_route_handles_garbage(monkeypatch):
    _patch_llm(monkeypatch, "我不知道你说什么")
    assert llm_route("x", ACCOUNTS) is None


def test_llm_route_chat_without_topic_defaults_unclassified(monkeypatch):
    _patch_llm(monkeypatch, '{"route":"chat","account_id":null}')
    assert llm_route("今天天气", ACCOUNTS) == {"route": "chat", "topic": "未归类"}


def test_llm_route_chat_returns_topic_and_detail(monkeypatch):
    _patch_llm(monkeypatch,
               '{"route":"chat","topic":"选品推荐","detail":"问该选什么品类"}')
    out = llm_route("这个类目能做吗", ACCOUNTS)
    assert out["route"] == "chat" and out["topic"] == "选品推荐"
    assert out["detail"] == "问该选什么品类"


def test_llm_route_rejects_topic_outside_taxonomy(monkeypatch):
    _patch_llm(monkeypatch, '{"route":"chat","topic":"随便编的"}')
    assert llm_route("x", ACCOUNTS)["topic"] == "未归类"


def test_llm_route_unknown_topic_keeps_proposed_label(monkeypatch):
    """词表没覆盖 → topic=未归类，但保留 LLM 自拟的 new_topic（用于发现新需求）。"""
    _patch_llm(monkeypatch,
               '{"route":"chat","topic":"未归类","new_topic":"私域运营","detail":"问私域转化"}')
    out = llm_route("怎么提升私域转化", ACCOUNTS)
    assert out["topic"] == "未归类"
    assert out["new_topic"] == "私域运营"
    assert out["detail"] == "问私域转化"


def test_llm_route_ignores_new_topic_when_known(monkeypatch):
    _patch_llm(monkeypatch, '{"route":"chat","topic":"选品推荐","new_topic":"多余"}')
    out = llm_route("x", ACCOUNTS)
    assert out["topic"] == "选品推荐" and "new_topic" not in out


def test_llm_route_without_llm(monkeypatch):
    import src.llm.client as client_mod
    monkeypatch.setattr(client_mod, "available", lambda: False)
    assert llm_route("x", ACCOUNTS) is None
