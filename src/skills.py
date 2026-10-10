"""技能（Skill）配置：可持久化的知识库，教 agent 什么情况下调哪个工具。

每个 skill 定义：
  name           技能名
  root_cause_id  关联的根因（可选）
  when           触发条件（大白话：什么情况下该用这个 skill）
  tool           要调用的工具名（见 llm/supplementary.py 的 TOOL_REGISTRY）
  tool_description 工具能查到什么
  confirm_if     查出来什么样 → 证实
  reject_if      查出来什么样 → 排除

用户可在 Web 的「技能配置」页导入/编辑自己的 skills，存于 config/skills.json。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_PATH = PROJECT_ROOT / "config" / "skills.json"

DEFAULT_SKILLS: list[dict] = [
    {
        "name": "素材疲劳/衰退",
        "root_cause_id": "RC01",
        "when": "当点击率(CTR)下降，怀疑某条素材投放过久、出现疲劳衰退时",
        "tool": "creative_ctr_trend",
        "tool_description": "查询某条素材近30天的点击率(CTR)趋势",
        "confirm_if": "CTR 后半段比前半段下降超过 10%",
        "reject_if": "CTR 平稳或上升",
    },
    {
        "name": "出价/预算调整",
        "root_cause_id": "RC02",
        "when": "当展示效率下降或广告花费激增，怀疑出价/预算被调高时",
        "tool": "bid_change_log",
        "tool_description": "查询出价/预算的变更记录",
        "confirm_if": "有出价/预算上调记录",
        "reject_if": "无出价/预算变更记录",
    },
    {
        "name": "落地页/直播间承接差",
        "root_cause_id": "RC03",
        "when": "当转化率(CVR)或下单率下降，怀疑直播间/落地页承接能力变差时",
        "tool": "live_room_metrics",
        "tool_description": "查询直播间平均停留时长、互动率",
        "confirm_if": "停留时长或互动率明显下滑",
        "reject_if": "停留/互动正常",
    },
    {
        "name": "商品/价格问题",
        "root_cause_id": "RC04",
        "when": "当客单价或下单率下降，怀疑商品涨价/缺货/差评变多时",
        "tool": "product_price",
        "tool_description": "查询商品价格、库存、评价变化",
        "confirm_if": "存在涨价/缺货/差评激增",
        "reject_if": "商品侧无异常",
    },
    {
        "name": "大盘/竞争变化",
        "root_cause_id": "RC05",
        "when": "当展示效率下降且 CTR 也小幅下降，怀疑行业大盘竞争加剧时",
        "tool": "market_cpm",
        "tool_description": "查询行业大盘的广告成本(CPM)走势",
        "confirm_if": "行业大盘广告成本上升、竞争加剧",
        "reject_if": "大盘平稳",
    },
    {
        "name": "大促前后效应",
        "root_cause_id": "RC06",
        "when": "数据波动疑似周期性，怀疑处于大促/节假日前后时",
        "tool": "promo_calendar",
        "tool_description": "查询营销日历、大促节点",
        "confirm_if": "处于大促/节假日前后",
        "reject_if": "无大促节点",
    },
    {
        "name": "流量质量下降",
        "root_cause_id": "RC07",
        "when": "当转化率(CVR)下降但点击率(CTR)正常，怀疑买到的流量质量变差时",
        "tool": "traffic_source_distribution",
        "tool_description": "查询流量来源/人群包分布",
        "confirm_if": "低质流量位或人群占比上升",
        "reject_if": "流量来源/人群结构无显著变化",
    },
    {
        "name": "结构风险/过度集中",
        "root_cause_id": "RC08",
        "when": "当结构集中度上升，怀疑预算过度集中在某一条素材时",
        "tool": "cost_share_trend",
        "tool_description": "查询某条素材消耗占账户预算比例的趋势",
        "confirm_if": "单一素材消耗占比持续上升（>15%）",
        "reject_if": "占比平稳",
    },
]


def load_skills() -> list[dict]:
    """读取用户配置的 skills；不存在或为空则用默认。"""
    if SKILLS_PATH.exists():
        try:
            data = json.loads(SKILLS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return [dict(s) for s in DEFAULT_SKILLS]


def save_skills(skills: list[dict]) -> None:
    SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKILLS_PATH.write_text(
        json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def skill_by_root_cause() -> dict[str, dict]:
    """root_cause_id → skill 映射（供确定性兜底路径使用）。"""
    return {s["root_cause_id"]: s for s in load_skills() if s.get("root_cause_id")}
