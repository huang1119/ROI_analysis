"""诊断报告生成。

- 多因：agent 依据技能库自主调工具取证 → 判断 → 大白话报告
- 单因：直接综合证据出报告
- 无 LLM：确定性兜底模板
"""
from __future__ import annotations

import pandas as pd

from ..diagnosis.root_causes import ROOT_CAUSE_BY_ID
from ..observability import record_fallback
from ..skills import load_skills
from .agent import run_agent
from .client import available, chat
from .supplementary import TOOL_SCHEMAS, execute_tool, fetch_supplementary

# 因子 → 大白话解释
FACTOR_PLAIN = {
    "展示效率": "花同样的钱能买到多少曝光",
    "CTR": "广告被点击的比例",
    "CVR": "点击后真正转化的比例",
    "下单率": "转化后真正下单的比例",
    "客单价": "平均每单多少钱",
    "结构集中度": "预算是否过度集中在某条素材",
    "消耗规模": "广告总花费",
}

_PLAIN_REPORT_RULES = (
    "用大白话写报告，避免专业术语；必须用时用括号解释，例如："
    "CTR=广告被点击的比例、CVR=点击后真正转化的比例、ROI=投入产出比、"
    "展示效率=花同样的钱能买来多少曝光、客单价=平均每单多少钱。\n"
    "不要使用 RC 编号、z-score、漏斗、多因共振 等术语。\n"
    "报告结构：\n"
    "1. 【一句话结论】到底哪里出了问题，是一个原因还是多个原因\n"
    "2. 【发生了什么】用大白话描述哪些数据变了、变了多少\n"
    "3. 【怎么判断的】结合查证的数据，说明为什么认定是这些原因、排除了哪些候选\n"
    "4. 【建议怎么做】2~4 条直接能执行的动作，按优先级排\n"
    "不要编造没有的数据；标注为『模拟数据』的仅供参考。"
)

AGENT_SYSTEM = (
    "你是一名电商广告投放分析师，读者是不懂技术的运营人员。\n"
    "你可以调用工具来查证数据。调用规则：\n"
    "1. 每个【技能】里的『触发条件』告诉你在什么情况下该用哪个工具，"
    "只调用与候选原因相关的工具，不要一次把工具全调一遍；\n"
    "2. 拿到查证结果后，对照技能里的『证实条件/排除条件』判断候选是否成立；\n"
    "3. 判断清楚后，给出最终结论。\n\n" + _PLAIN_REPORT_RULES
)

SINGLE_SYSTEM = (
    "你是一名电商广告投放分析师，读者是不懂技术的运营人员。\n" + _PLAIN_REPORT_RULES
)


def _severity(z: float) -> str:
    a = abs(z)
    if a < 2:
        return "基本正常"
    if a < 4:
        return "明显变化"
    return "剧烈变化"


def _top_creative(result: dict) -> str | None:
    for dd in result["drilldowns"].values():
        if dd is not None and not dd.empty:
            return dd.iloc[0]["creative_id"]
    return None


def _evidence_text(result: dict) -> str:
    lines = ["【数据变化（大白话）】"]
    for _, r in result["evidence"].iterrows():
        plain = FACTOR_PLAIN.get(r["factor"], r["factor"])
        pct = r["pct_change"] * 100 if r["pct_change"] == r["pct_change"] else 0.0
        direction = "下降" if pct < 0 else "上升"
        lines.append(f"- {r['factor']}（{plain}）：{direction} {abs(pct):.1f}%，{_severity(r['zscore'])}")
    return "\n".join(lines)


def _candidates_text(candidates: pd.DataFrame) -> str:
    lines = ["【候选原因】"]
    for _, row in candidates.iterrows():
        lines.append(f"- {row['name']}（可能性得分 {row['score']:.2f}）")
    return "\n".join(lines)


def _skills_text() -> str:
    """把全部 skill 都交给 agent，由 agent 按『触发条件』自主选择用哪些。"""
    lines = ["【技能库（什么情况下该调哪个工具）】"]
    for s in load_skills():
        lines.append(
            f"- 技能：{s.get('name', '')}\n"
            f"  触发条件：{s.get('when', '')}\n"
            f"  调用工具：{s.get('tool', '')}（{s.get('tool_description', '')}）\n"
            f"  证实条件：{s.get('confirm_if', '')}；排除条件：{s.get('reject_if', '')}"
        )
    return "\n".join(lines)


def _template_report(result: dict, candidates: pd.DataFrame, supplementary: dict) -> str:
    mode = result["decision"]["mode"]
    names = " + ".join(candidates["name"].tolist())
    lines = [f"【结论】账户 {result['account_name']} 投放出现异常"
             f"（{'一个原因' if mode == 'single' else '多个原因叠加'}）：{names}"]
    lines.append("\n" + _evidence_text(result))

    lines.append("\n【怎么判断的】")
    for _, row in candidates.iterrows():
        info = (supplementary or {}).get(row["id"], {})
        lines.append(f"- {row['name']}（可能性 {row['score']:.2f}）：{info.get('判定', '待查证')}")

    lines.append("\n【建议怎么做】")
    for i, (_, row) in enumerate(candidates.iterrows(), 1):
        rc = ROOT_CAUSE_BY_ID.get(row["id"])
        if rc:
            lines.append(f"{i}. {rc.suggestion}")
    return "\n".join(lines)


def generate_report(result: dict, df: pd.DataFrame, top_n: int = 3) -> str:
    mode = result["decision"]["mode"]
    if mode == "none":
        return f"账户 {result['account_name']} 近期投放数据没有明显异常，各环节都在正常范围内。"

    candidates = result["scores"].head(top_n if mode == "multiple" else 1)
    candidate_ids = candidates["id"].tolist()

    if not available():
        record_fallback("template_report")
        supplementary = fetch_supplementary(df, result["account_id"], candidate_ids, result["drilldowns"])
        return _template_report(result, candidates, supplementary)

    if mode == "multiple":
        account_id = result["account_id"]
        top_creative = _top_creative(result)
        context = "\n\n".join([
            f"账户：{result['account_name']}（{result['account_id']}）",
            f"对比窗口：近 {result['recent_days']} 天 vs 前 {result['baseline_days']} 天基线",
            _evidence_text(result),
            _candidates_text(candidates),
            _skills_text(),
            f"【最可疑素材】{top_creative or '未知'}",
        ])
        return run_agent(
            AGENT_SYSTEM,
            context,
            tools=TOOL_SCHEMAS,
            execute=lambda name, args: execute_tool(name, args, df, account_id, top_creative),
        )

    # 单因：直接综合证据出报告（附带该原因的确定性查证）
    supplementary = fetch_supplementary(df, result["account_id"], candidate_ids, result["drilldowns"])
    top = candidates.iloc[0]
    info = supplementary.get(top["id"], {})
    context = "\n\n".join([
        f"账户：{result['account_name']}（{result['account_id']}）",
        _evidence_text(result),
        f"主要结论：{top['name']}（可能性得分 {top['score']:.2f}）",
        f"查证结果：{info}",
    ])
    return chat([
        {"role": "system", "content": SINGLE_SYSTEM},
        {"role": "user", "content": context + "\n\n请按系统提示的结构输出报告。"},
    ])
