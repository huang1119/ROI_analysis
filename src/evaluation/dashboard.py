"""缺口信号聚合（design.md §8.6 一期：计数级聚合）。

从 Langfuse API 拉取并做客户端聚合，产出自建看板所需的计数：
    - 兜底触发次数（按 fallback_type）
    - 工具调用失败分布（按工具）
    - route 分布
    - 总 trace 数
每个查询独立 try/except，Langfuse 未配置或网络异常时优雅降级为 0/空。
"""
from __future__ import annotations

from typing import Any, Optional


def _client(client=None):
    if client is not None:
        return client
    from ..observability import get_client

    return get_client()


def _val(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _score_label(score: Any) -> Any:
    """CATEGORICAL 分数的字符串存在 string_value，value 是 0.0；优先取前者。"""
    return _val(score, "string_value") or _val(score, "value")


def _count_scores(client, name: str, limit: int = 100) -> dict:
    scores = client.api.scores.get_many(name=name, limit=limit)
    counts: dict = {}
    for s in (scores.data or []):
        v = _score_label(s)
        if v is None:
            continue
        counts[str(v)] = counts.get(str(v), 0) + 1
    return counts


def aggregate_signals(client=None, *, trace_limit: int = 100, obs_limit: int = 100) -> dict:
    """聚合线上监测信号。返回可 JSON 序列化的 dict。

    Langfuse API 的 limit 上限为 100；作品集阶段流量小，100 条足够。
    """
    c = _client(client)
    if c is None:
        return {"enabled": False, "error": "未配置 Langfuse"}

    out: dict = {
        "enabled": True,
        "error": None,
        "total_traces": 0,
        "fallback_counts": {},
        "fallback_topics": {},
        "fallback_topic_examples": {},
        "new_topic_counts": {},
        "new_topic_examples": {},
        "tool_failures": {},
        "route_distribution": {},
    }

    # 兜底触发次数（按兜底类型）
    try:
        out["fallback_counts"] = _count_scores(c, "fallback_type", limit=min(100, trace_limit))
    except Exception as e:  # noqa: BLE001
        out["error"] = out["error"] or f"fallback scores: {e}"

    # 兜底归因（按话题）——回答「开发者该往哪个方向迭代」
    try:
        out["fallback_topics"] = _count_scores(c, "topic", limit=min(100, trace_limit))
    except Exception as e:  # noqa: BLE001
        out["error"] = out["error"] or f"topic scores: {e}"

    # 工具调用失败分布：TOOL 观测的 metadata.status == "error"
    try:
        obs = c.api.observations.get_many(
            type="TOOL", limit=min(100, obs_limit), fields="id,type,name,metadata",
        )
        for o in (obs.data or []):
            meta = _val(o, "metadata") or {}
            if _val(meta, "status") == "error":
                tool = _val(meta, "tool") or _val(o, "name") or "unknown"
                out["tool_failures"][tool] = out["tool_failures"].get(tool, 0) + 1
    except Exception as e:  # noqa: BLE001
        out["error"] = out["error"] or f"tool observations: {e}"

    # route 分布 + 总 trace 数 + 各话题的 detail 示例（最多 3 条）
    try:
        traces = c.api.trace.list(limit=min(100, trace_limit), fields="id,name,metadata")
        examples: dict = {}
        examples_new: dict = {}
        for t in (traces.data or []):
            out["total_traces"] += 1
            meta = _val(t, "metadata") or {}
            route = _val(meta, "route") or "unknown"
            out["route_distribution"][route] = out["route_distribution"].get(route, 0) + 1
            topic = _val(meta, "topic")
            detail = _val(meta, "topic_detail")
            if topic and detail:
                bucket = examples.setdefault(str(topic), [])
                if len(bucket) < 3 and detail not in bucket:
                    bucket.append(str(detail))
            # LLM 自拟的新标签（词表未覆盖）→ 用于发现新需求
            new_topic = _val(meta, "new_topic")
            if new_topic:
                nt = str(new_topic)
                out["new_topic_counts"][nt] = out["new_topic_counts"].get(nt, 0) + 1
                ex = examples_new.setdefault(nt, [])
                if detail and len(ex) < 2 and str(detail) not in ex:
                    ex.append(str(detail))
        out["fallback_topic_examples"] = examples
        out["new_topic_examples"] = examples_new
    except Exception as e:  # noqa: BLE001
        out["error"] = out["error"] or f"traces: {e}"

    return out


def recent_experiments(client=None, *, limit: int = 10) -> dict:
    """最近实验（黄金集跑批）列表，供看板「回归入口」展示。"""
    c = _client(client)
    if c is None:
        return {"enabled": False, "experiments": []}

    from datetime import datetime, timedelta, timezone

    try:
        exp = c.api.experiments.list(
            from_start_time=datetime.now(timezone.utc) - timedelta(days=30),
            limit=limit,
        )
        rows = []
        for e in (exp.data or []):
            rows.append({
                "name": _val(e, "name"),
                "item_count": _val(e, "item_count"),
                "start_time": str(_val(e, "start_time") or ""),
            })
        return {"enabled": True, "experiments": rows}
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "experiments": [], "error": str(e)}
