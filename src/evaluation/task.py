"""回归 task：把一次诊断跑成结构化输出（design.md §8.8）。

task 输出字段：
    account_id     账户
    decision       决策模式（single/multiple/none）
    root_cause     首要根因编码（如 RC08）
    deviated_stage 偏离最显著的漏斗环节（展示效率/CTR/CVR/下单率/客单价）
    evidence       偏离 Top-N 证据（factor/zscore/direction）
    answer         自然语言报告（LLM 生成；with_report=False 时为空）

with_report=False 时只跑确定性诊断，不调 LLM——供离线单测与快速跑批使用。
"""
from __future__ import annotations

import pandas as pd

from ..diagnosis.engine import diagnose
from ..llm.report import generate_report
from ..llm.router import route_message
from ..observability import start_recording, stop_recording
from ..topics import classify as classify_topic

# 漏斗五环节（deviated_stage 只在这五个里取，排除结构集中度/消耗规模等辅助因子）
FUNNEL_FACTORS = ["展示效率", "CTR", "CVR", "下单率", "客单价"]


def top_root_cause(result: dict) -> str | None:
    scores = result.get("scores")
    if scores is None or len(scores) == 0:
        return None
    return scores.iloc[0]["id"]


def top_deviated_stage(result: dict) -> str | None:
    ev = result.get("evidence")
    if ev is None or ev.empty:
        return None
    ev = ev[ev["factor"].isin(FUNNEL_FACTORS)]
    if ev.empty:
        return None
    ev = ev.copy()
    ev["abs_z"] = ev["zscore"].abs()
    return ev.sort_values("abs_z", ascending=False).iloc[0]["factor"]


def _top_evidence(result: dict, top_n: int = 3) -> list[dict]:
    ev = result.get("evidence")
    if ev is None or ev.empty:
        return []
    ev = ev.copy()
    ev["abs_z"] = ev["zscore"].abs()
    ev = ev.sort_values("abs_z", ascending=False).head(top_n)
    return [
        {
            "factor": row["factor"],
            "zscore": round(float(row["zscore"]), 3),
            "direction": row["direction"],
        }
        for _, row in ev.iterrows()
    ]


def run_diagnosis_task(
    df: pd.DataFrame,
    account_id: str,
    *,
    with_report: bool = True,
    report_fn=generate_report,
) -> dict:
    """对指定账户跑一次诊断，返回结构化输出（含 tool_calls / fallback_type）。"""
    result = diagnose(df, account_id)
    answer = ""
    if with_report:
        start_recording()
        try:
            answer = report_fn(result, df)
        finally:
            events = stop_recording()
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        fallbacks = [e["value"] for e in events if e["type"] == "fallback"]
    else:
        tool_calls, fallbacks = [], []

    return {
        "task_type": "diagnosis",
        "account_id": account_id,
        "route": "diagnose",
        "decision": result["decision"]["mode"],
        "root_cause": top_root_cause(result),
        "deviated_stage": top_deviated_stage(result),
        "evidence": _top_evidence(result),
        "tool_calls": tool_calls,
        "fallback_type": fallbacks[-1] if fallbacks else None,
        "answer": answer,
    }


def run_chat_task(
    question: str,
    *,
    accounts: list[dict],
    llm_available: bool | None = None,
) -> dict:
    """对话路由用例：只做意图路由判定，不实际调 LLM（保证确定性）。

    用于验证兼底路径（keyword_miss / no_llm_available）。
    """
    if llm_available is None:
        from ..llm.client import available as _available

        llm_available = _available()
    decision = route_message(question, accounts=accounts, llm_available=llm_available)
    fallback_type = decision.get("fallback_type")
    return {
        "task_type": "chat",
        "account_id": decision.get("account_id"),
        "route": decision["route"],
        "decision": decision["route"],
        "root_cause": None,
        "deviated_stage": None,
        "evidence": [],
        "tool_calls": [],
        "fallback_type": fallback_type,
        "topic": classify_topic(question) if fallback_type else None,
        "answer": "",
    }


def run_task(
    df: pd.DataFrame,
    item_input: dict,
    *,
    accounts: list[dict],
    llm_available: bool | None = None,
    with_report: bool = True,
) -> dict:
    """统一用例调度。

    - input 带 account_id → 直接跑诊断
    - input 带 question → 先路由：路由到诊断就真跑诊断（线上转化用例可重放），
      否则只返回路由/兼底判定
    """
    if "account_id" in item_input:
        return run_diagnosis_task(df, item_input["account_id"], with_report=with_report)

    question = item_input.get("question")
    if question is None:
        raise ValueError(f"未知用例 input：{item_input}")

    if llm_available is None:
        from ..llm.client import available as _available

        llm_available = _available()
    decision = route_message(question, accounts=accounts, llm_available=llm_available)

    if decision["route"] == "diagnose":
        out = run_diagnosis_task(df, decision["account_id"], with_report=with_report)
        out["question"] = question
        return out
    return run_chat_task(question, accounts=accounts, llm_available=llm_available)
