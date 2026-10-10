"""取证工具：数据查询函数 + 供 agent 调用的工具 schema + 执行器。

- 数据支撑（真实计算）：素材 CTR 趋势、消耗占比趋势
- 模拟（标注 mock）：直播间承接、流量质量、出价日志、商品、大盘、营销日历

工具通过 TOOL_REGISTRY 注册；TOOL_SCHEMAS 描述给 LLM（function calling）；
execute_tool 供 agent 循环执行工具调用。
"""
from __future__ import annotations

import pandas as pd

from ..skills import skill_by_root_cause


def creative_ctr_trend(df: pd.DataFrame, creative_id: str, days: int = 30) -> dict:
    """某素材近 N 天 CTR 趋势（前一半 vs 后一半）。"""
    c = df[df["creative_id"] == creative_id].sort_values("date").tail(days).copy()
    c["ctr"] = c["click_cnt"] / c["show_cnt"]
    half = len(c) // 2
    first = c["ctr"].iloc[:half].mean()
    second = c["ctr"].iloc[half:].mean()
    change = (second / first - 1) if first else 0.0
    verdict = "下降" if change < -0.10 else ("上升" if change > 0.10 else "平稳")
    return {
        "素材": creative_id,
        "近30天CTR前半段": round(float(first), 4),
        "近30天CTR后半段": round(float(second), 4),
        "变化": f"{change:+.1%}",
        "判定": f"CTR {verdict}",
    }


def cost_share_trend(df: pd.DataFrame, account_id: str, creative_id: str, days: int = 30) -> dict:
    """某素材消耗占账户比例的趋势（首尾对比）。"""
    acc = df[df["advertiser_id"] == account_id].sort_values("date")
    acc = acc[acc["date"] >= acc["date"].max() - pd.Timedelta(days=days - 1)]
    daily_total = acc.groupby("date")["stat_cost"].sum()
    daily_c = acc[acc["creative_id"] == creative_id].groupby("date")["stat_cost"].sum()
    share = (daily_c / daily_total).dropna()
    first = share.iloc[: max(1, len(share) // 2)].mean()
    second = share.iloc[len(share) // 2:].mean()
    change = (second / first - 1) if first else 0.0
    verdict = "上升" if change > 0.15 else ("下降" if change < -0.15 else "平稳")
    return {
        "素材": creative_id,
        "前半段消耗占比": f"{first:.1%}",
        "后半段消耗占比": f"{second:.1%}",
        "变化": f"{change:+.1%}",
        "判定": f"消耗占比 {verdict}",
    }


def _mock(verdict: str, extra: dict | None = None) -> dict:
    d = {"数据来源": "模拟数据（MVP，二期接真实 API）", "判定": verdict}
    if extra:
        d.update(extra)
    return d


def live_room_metrics(*_) -> dict:
    return _mock("承接数据暂无异常", {"平均停留": "2分40秒", "互动率": "6.2%"})


def bid_change_log(*_) -> dict:
    return _mock("近期无出价/预算变更记录")


def product_price(*_) -> dict:
    return _mock("商品价格/库存/评价无异常", {"价格变动": "无", "差评新增": "0"})


def market_cpm(*_) -> dict:
    return _mock("行业大盘 CPM 平稳，未现竞争加剧")


def promo_calendar(*_) -> dict:
    return _mock("近期无大促节点")


def traffic_source_distribution(*_) -> dict:
    return _mock("人群包/来源分布无显著变化", {"新客占比": "41%", "通投占比": "58%"})


# 工具注册表：统一签名 (df, account_id, creative_id) -> dict
TOOL_REGISTRY = {
    "creative_ctr_trend": lambda df, aid, cid: creative_ctr_trend(df, cid),
    "cost_share_trend": lambda df, aid, cid: cost_share_trend(df, aid, cid),
    "live_room_metrics": lambda df, aid, cid: live_room_metrics(),
    "bid_change_log": lambda df, aid, cid: bid_change_log(),
    "product_price": lambda df, aid, cid: product_price(),
    "market_cpm": lambda df, aid, cid: market_cpm(),
    "promo_calendar": lambda df, aid, cid: promo_calendar(),
    "traffic_source_distribution": lambda df, aid, cid: traffic_source_distribution(),
}


def _schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "creative_id": {
                        "type": "string",
                        "description": "素材ID，可选；不填则查最可疑的那条素材",
                    }
                },
                "required": [],
            },
        },
    }


# 供 LLM function calling 使用的工具描述
TOOL_SCHEMAS = [
    _schema("creative_ctr_trend", "查询某条素材近30天的点击率(CTR)趋势，用于判断素材是否疲劳衰退"),
    _schema("cost_share_trend", "查询某条素材消耗占账户预算比例的趋势，用于判断预算是否过度集中"),
    _schema("live_room_metrics", "查询直播间平均停留时长与互动率，用于判断承接能力"),
    _schema("bid_change_log", "查询出价/预算的变更记录"),
    _schema("product_price", "查询商品价格、库存、评价变化"),
    _schema("market_cpm", "查询行业大盘广告成本(CPM)走势"),
    _schema("promo_calendar", "查询营销日历、大促节点"),
    _schema("traffic_source_distribution", "查询流量来源/人群包分布，用于判断流量质量"),
]


def execute_tool(name: str, args: dict, df: pd.DataFrame, account_id: str, top_creative: str | None) -> dict:
    """执行一次工具调用。"""
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"error": f"未知工具: {name}"}
    cid = args.get("creative_id") or top_creative
    return tool(df, account_id, cid)


def fetch_supplementary(
    df: pd.DataFrame,
    account_id: str,
    top_cause_ids: list[str],
    drilldowns: dict,
) -> dict[str, dict]:
    """确定性兜底：按 skill 只对候选根因查针对性数据。返回 {cause_id: 取证结果}。"""
    def _top_creative():
        for dd in drilldowns.values():
            if dd is not None and not dd.empty:
                return dd.iloc[0]["creative_id"]
        return None

    cid = _top_creative()
    mapping = skill_by_root_cause()
    out: dict[str, dict] = {}
    for rc_id in top_cause_ids:
        skill = mapping.get(rc_id)
        if skill is None:
            continue
        tool = TOOL_REGISTRY.get(skill["tool"])
        if tool is None:
            continue
        out[rc_id] = tool(df, account_id, cid)
    return out
