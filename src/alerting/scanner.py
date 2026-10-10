"""检测层：D+1 定时扫描所有账户，筛出存在 ROI 异常的账户。"""
from __future__ import annotations

import pandas as pd

from ..diagnosis.engine import diagnose


def scan_all(
    df: pd.DataFrame,
    recent_days: int = 7,
    baseline_days: int = 21,
    only_anomalous: bool = True,
) -> list[dict]:
    """扫描全部账户，返回诊断结果列表（默认只保留有异常的）。"""
    results = []
    for aid in sorted(df["advertiser_id"].unique()):
        r = diagnose(df, aid, recent_days=recent_days, baseline_days=baseline_days)
        if only_anomalous and r["decision"]["mode"] == "none":
            continue
        results.append(r)
    return results
