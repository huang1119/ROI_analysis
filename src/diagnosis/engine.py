"""诊断引擎编排：数据 → 证据层 → 推理层 → 决策层。"""
from __future__ import annotations

import pandas as pd

from .baseline import detect_account_factors, drilldown
from .scoring import score_root_causes, decide

# 证据层下钻的偏离阈值：|z| 超过该值的因子才做维度下钻
DRILLDOWN_Z_THRESHOLD = 2.0
MAX_DRILLDOWN_FACTORS = 3


def diagnose(
    df: pd.DataFrame,
    account_id: str,
    recent_days: int = 7,
    baseline_days: int = 21,
) -> dict:
    """对指定账户执行确定性诊断（不含 LLM 层）。"""
    account_name = df.loc[df["advertiser_id"] == account_id, "advertiser_name"].iloc[0]

    evidence = detect_account_factors(df, account_id, recent_days, baseline_days)
    scores = score_root_causes(evidence)
    decision = decide(scores)

    # 选偏离最显著的因子做下钻（漏斗因子 + 结构集中度）
    flagged = evidence[evidence["zscore"].abs() >= DRILLDOWN_Z_THRESHOLD]
    flagged = flagged.reindex(flagged["zscore"].abs().sort_values(ascending=False).index)
    flagged = flagged.head(MAX_DRILLDOWN_FACTORS)

    drilldowns = {}
    for factor in flagged["factor"]:
        try:
            drilldowns[factor] = drilldown(
                df, account_id, factor, recent_days, baseline_days, level="creative"
            )
        except Exception:
            drilldowns[factor] = None

    return {
        "account_id": account_id,
        "account_name": account_name,
        "recent_days": recent_days,
        "baseline_days": baseline_days,
        "evidence": evidence,
        "scores": scores,
        "decision": decision,
        "drilldowns": drilldowns,
    }
