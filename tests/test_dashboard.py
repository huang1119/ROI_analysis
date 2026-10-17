"""测试 src/evaluation/dashboard：信号聚合 + 优雅降级。"""
from types import SimpleNamespace

from src.evaluation.dashboard import aggregate_signals, recent_experiments


def _fake_client():
    """构造一个最小 Langfuse client mock，验证聚合逻辑。"""
    # CATEGORICAL 分数：字符串在 string_value，value 是 0.0
    fallback_scores = SimpleNamespace(data=[
        SimpleNamespace(string_value="keyword_miss", value=0.0),
        SimpleNamespace(string_value="keyword_miss", value=0.0),
        SimpleNamespace(string_value="template_report", value=0.0),
    ])
    topic_scores = SimpleNamespace(data=[
        SimpleNamespace(string_value="选品推荐", value=0.0),
        SimpleNamespace(string_value="选品推荐", value=0.0),
        SimpleNamespace(string_value="天气/无关查询", value=0.0),
    ])
    obs = SimpleNamespace(
        data=[
            SimpleNamespace(name="tool:cost_share_trend",
                            metadata={"tool": "cost_share_trend", "status": "error"}),
            SimpleNamespace(name="tool:live_room_metrics",
                            metadata={"tool": "live_room_metrics", "status": "ok"}),
            SimpleNamespace(name="tool:bid_change_log",
                            metadata={"tool": "bid_change_log", "status": "error"}),
        ]
    )
    traces = SimpleNamespace(
        data=[
            SimpleNamespace(name="chat", metadata={"route": "diagnose"}),
            SimpleNamespace(name="chat", metadata={"route": "diagnose"}),
            SimpleNamespace(name="chat", metadata={"route": "chat"}),
            SimpleNamespace(name="cli.ask", metadata={}),
        ]
    )
    experiments = SimpleNamespace(
        data=[
            SimpleNamespace(name="v1", item_count=2, start_time="2026-10-14T00:00:00"),
        ]
    )

    class API:
        scores = SimpleNamespace(
            get_many=lambda name=None, **k: topic_scores if name == "topic" else fallback_scores)
        observations = SimpleNamespace(get_many=lambda **k: obs)
        trace = SimpleNamespace(list=lambda **k: traces)
        experiments = SimpleNamespace(list=lambda **k: experiments)

    return SimpleNamespace(api=API())


def test_aggregate_signals_counts(monkeypatch):
    client = _fake_client()
    out = aggregate_signals(client)
    assert out["enabled"] is True
    assert out["total_traces"] == 4
    assert out["fallback_counts"] == {"keyword_miss": 2, "template_report": 1}
    assert out["fallback_topics"] == {"选品推荐": 2, "天气/无关查询": 1}
    assert out["tool_failures"] == {"cost_share_trend": 1, "bid_change_log": 1}
    assert out["route_distribution"] == {"diagnose": 2, "chat": 1, "unknown": 1}


def test_aggregate_signals_topic_examples():
    traces = SimpleNamespace(data=[
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐", "topic_detail": "问该选什么品类"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐", "topic_detail": "哪个品好卖"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐", "topic_detail": "上什么货合适"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐", "topic_detail": "这条不该被收录"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "天气/无关查询", "topic_detail": "查今天天气"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐"}),          # 无 detail → 忽略
        SimpleNamespace(metadata={"route": "diagnose"}),
    ])

    class API:
        scores = SimpleNamespace(get_many=lambda name=None, **k: SimpleNamespace(data=[]))
        observations = SimpleNamespace(get_many=lambda **k: SimpleNamespace(data=[]))
        trace = SimpleNamespace(list=lambda **k: traces)

    out = aggregate_signals(SimpleNamespace(api=API()))
    assert out["fallback_topic_examples"]["选品推荐"] == [
        "问该选什么品类", "哪个品好卖", "上什么货合适"]     # 最多 3 条
    assert out["fallback_topic_examples"]["天气/无关查询"] == ["查今天天气"]


def test_aggregate_signals_new_topics():
    """LLM 自拟的 new_topic 应单独聚合，供发现新需求。"""
    traces = SimpleNamespace(data=[
        SimpleNamespace(metadata={"route": "chat", "topic": "未归类", "new_topic": "私域运营", "topic_detail": "问私域转化"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "未归类", "new_topic": "私域运营", "topic_detail": "私域怎么起盘"}),
        SimpleNamespace(metadata={"route": "chat", "topic": "选品推荐"}),
    ])

    class API:
        scores = SimpleNamespace(get_many=lambda name=None, **k: SimpleNamespace(data=[]))
        observations = SimpleNamespace(get_many=lambda **k: SimpleNamespace(data=[]))
        trace = SimpleNamespace(list=lambda **k: traces)

    out = aggregate_signals(SimpleNamespace(api=API()))
    assert out["new_topic_counts"] == {"私域运营": 2}
    assert out["new_topic_examples"]["私域运营"] == ["问私域转化", "私域怎么起盘"]


def test_recent_experiments(monkeypatch):
    out = recent_experiments(_fake_client())
    assert out["enabled"] is True
    assert len(out["experiments"]) == 1
    assert out["experiments"][0]["name"] == "v1"
    assert out["experiments"][0]["item_count"] == 2


def test_aggregate_signals_graceful_without_client(monkeypatch):
    import src.evaluation.dashboard as dash
    monkeypatch.setattr(dash, "_client", lambda client=None: None)
    out = aggregate_signals()
    assert out["enabled"] is False


def test_recent_experiments_graceful_without_client(monkeypatch):
    import src.evaluation.dashboard as dash
    monkeypatch.setattr(dash, "_client", lambda client=None: None)
    out = recent_experiments()
    assert out["enabled"] is False
    assert out["experiments"] == []
