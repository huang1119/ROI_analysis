"""缺口归因：把用户问题归到可读的话题类别（design.md §8.2 缺口信号聚合）。

用途：兜底时记录「用户到底在问什么」，让开发者看到「选品推荐 触发兜底 37 次」
而不是 37 条孤立对话，从而锚定迭代方向。

分类方式为一期方案——关键词规则（确定性、零成本、可离线）；
词表可在 settings.json 的 `topics` 覆盖。语义聚类（embedding）是二期。
"""
from __future__ import annotations

UNCLASSIFIED = "未归类"

DEFAULT_TOPICS: list[dict] = [
    {"label": "选品推荐", "keywords": ["选品", "选款", "卖什么", "选什么", "好卖", "爆款", "上什么", "什么产品"]},
    {"label": "天气/无关查询", "keywords": ["天气", "气温", "温度", "下雨", "下雪", "几点", "星期几"]},
    {"label": "竞品/大盘", "keywords": ["竞品", "对手", "同行", "大盘", "行业趋势", "行业数据"]},
    {"label": "平台规则", "keywords": ["规则", "违规", "审核", "封号", "处罚", "限流"]},
    {"label": "内容/素材创作", "keywords": ["写文案", "文案", "脚本", "创意", "短视频", "直播话术", "标题"]},
    {"label": "定价/利润", "keywords": ["定价", "价格怎么", "卖多少钱", "毛利", "利润"]},
    {"label": "店铺运营", "keywords": ["店铺装修", "客服", "发货", "退换货", "评价管理", "售后"]},
    {"label": "闲聊/无关", "keywords": ["你是谁", "笑话", "写诗", "诗", "唱歌", "讲故事", "聊天"]},
]


def load_topics() -> list[dict]:
    """读取配置的 topics；未配置则用默认词表。"""
    try:
        from .settings import load_settings

        topics = load_settings().get("topics") or []
    except Exception:  # noqa: BLE001
        topics = []
    return topics if topics else DEFAULT_TOPICS


def classify(question: str, topics: list[dict] | None = None) -> str:
    """把问题归到话题标签；没命中任何词表则返回「未归类」。"""
    q = (question or "").lower()
    for t in (topics if topics is not None else load_topics()):
        for kw in t.get("keywords", []):
            if kw and kw.lower() in q:
                return t.get("label") or UNCLASSIFIED
    return UNCLASSIFIED
