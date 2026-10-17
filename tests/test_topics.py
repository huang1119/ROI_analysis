"""测试 src/topics：缺口归因话题分类。"""
import src.topics as topics


def test_classify_matches_known_topics():
    assert topics.classify("怎么选品") == "选品推荐"
    assert topics.classify("哪个电商产品好卖") == "选品推荐"
    assert topics.classify("今天天气怎么样") == "天气/无关查询"
    assert topics.classify("帮我写一首关于春天的诗") == "闲聊/无关"


def test_classify_unknown_returns_unclassified():
    assert topics.classify("为什么美妆旗舰店的ROI下降了") == "未归类"
    assert topics.classify("") == "未归类"
    assert topics.classify(None) == "未归类"


def test_classify_custom_topics():
    custom = [{"label": "售后", "keywords": ["退款"]}]
    assert topics.classify("我要退款", custom) == "售后"
    assert topics.classify("怎么选品", custom) == "未归类"


def test_load_topics_falls_back_to_default(monkeypatch):
    import src.settings as settings
    monkeypatch.setattr(settings, "load_settings", lambda: {})
    assert topics.load_topics() == topics.DEFAULT_TOPICS

    monkeypatch.setattr(settings, "load_settings",
                        lambda: {"topics": [{"label": "自定义", "keywords": ["x"]}]})
    assert topics.load_topics()[0]["label"] == "自定义"


def test_topics_survive_settings_roundtrip(tmp_path, monkeypatch):
    """settings.json 里的 topics 不该被 load_settings 丢掉。"""
    import src.settings as settings
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    settings.save_settings({"topics": [{"label": "X", "keywords": ["y"]}]})
    assert settings.load_settings()["topics"][0]["label"] == "X"
