"""证据层：漏斗分解 + 时序基线偏离检测 + 维度下钻。

对某个账户，计算五个漏斗环节（展示效率/CTR/CVR/下单率/客单价）
以及两个结构性信号（结构集中度、消耗规模）在「近期窗口」相对
「基线窗口」的稳健 z-score 偏离，并支持下钻定位到具体素材。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.schema import METRIC_COLS, FACTOR_COLUMN, compute_funnel

# 漏斗环节 → (分子列, 分母列)，用于「分子求和 / 分母求和」的聚合口径
FACTOR_PARTS = {
    "展示效率": ("show_cnt", "stat_cost"),
    "CTR": ("click_cnt", "show_cnt"),
    "CVR": ("convert_cnt", "click_cnt"),
    "下单率": ("pay_order_count", "convert_cnt"),
    "客单价": ("pay_amount", "pay_order_count"),
}

FUNNEL_FACTORS = list(FACTOR_PARTS.keys())


def robust_zscore(recent: np.ndarray, baseline: np.ndarray) -> float:
    """稳健 z-score：以基线中位数 + MAD(×1.4826) 为基准，比较近期中位数。"""
    med = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - med)))
    if mad == 0:
        mad = 1e-9
    return (float(np.median(recent)) - med) / (mad * 1.4826)


def _windows(df: pd.DataFrame, recent_days: int, baseline_days: int):
    """返回 (recent_df, baseline_df)，按日期切分两个窗口。"""
    max_date = df["date"].max()
    recent_start = max_date - pd.Timedelta(days=recent_days - 1)
    baseline_end = recent_start - pd.Timedelta(days=1)
    baseline_start = baseline_end - pd.Timedelta(days=baseline_days - 1)

    recent = df[df["date"] >= recent_start]
    baseline = df[(df["date"] >= baseline_start) & (df["date"] <= baseline_end)]
    return recent, baseline


def _ratio(daily: pd.DataFrame, num: str, den: str) -> pd.Series:
    """逐行计算 num/den，处理除零。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        r = daily[num] / daily[den]
    return r.replace([np.inf, -np.inf], np.nan)


def detect_account_factors(
    df: pd.DataFrame,
    account_id: str,
    recent_days: int = 7,
    baseline_days: int = 21,
) -> pd.DataFrame:
    """账户级证据：每个因子近期相对基线的偏离。

    返回 DataFrame，列：
        factor, baseline_med, recent_med, zscore, pct_change, direction
    """
    acc = df[df["advertiser_id"] == account_id]
    daily = acc.groupby("date")[METRIC_COLS].sum().reset_index()
    daily = compute_funnel(daily)
    recent, baseline = _windows(daily, recent_days, baseline_days)

    rows = []
    for factor, col in FACTOR_COLUMN.items():
        b = baseline[col].dropna().to_numpy()
        r = recent[col].dropna().to_numpy()
        if len(b) == 0 or len(r) == 0:
            continue
        z = robust_zscore(r, b)
        pct = float(np.median(r) / np.median(b) - 1) if np.median(b) != 0 else np.nan
        rows.append({
            "factor": factor,
            "baseline_med": float(np.median(b)),
            "recent_med": float(np.median(r)),
            "zscore": z,
            "pct_change": pct,
            "direction": "up" if z > 0 else "down",
        })

    # 结构集中度：每日 top1 素材消耗占比
    daily_conc = _top_share_series(acc)
    recent_c, baseline_c = _series_windows(daily_conc, recent_days, baseline_days)
    if len(baseline_c) and len(recent_c):
        z = robust_zscore(recent_c.to_numpy(), baseline_c.to_numpy())
        rows.append({
            "factor": "结构集中度",
            "baseline_med": float(np.median(baseline_c)),
            "recent_med": float(np.median(recent_c)),
            "zscore": z,
            "pct_change": float(np.median(recent_c) / np.median(baseline_c) - 1),
            "direction": "up" if z > 0 else "down",
        })

    # 消耗规模：每日总消耗
    daily_cost = daily.set_index("date")["stat_cost"]
    recent_s, baseline_s = _series_windows(daily_cost, recent_days, baseline_days)
    if len(baseline_s) and len(recent_s):
        z = robust_zscore(recent_s.to_numpy(), baseline_s.to_numpy())
        rows.append({
            "factor": "消耗规模",
            "baseline_med": float(np.median(baseline_s)),
            "recent_med": float(np.median(recent_s)),
            "zscore": z,
            "pct_change": float(np.median(recent_s) / np.median(baseline_s) - 1),
            "direction": "up" if z > 0 else "down",
        })

    return pd.DataFrame(rows)


def _top_share_series(acc: pd.DataFrame) -> pd.Series:
    """每日 top1 素材消耗占比。"""
    daily_total = acc.groupby("date")["stat_cost"].sum()
    daily_top = acc.groupby("date")["stat_cost"].max()
    return daily_top / daily_total


def _series_windows(s: pd.Series, recent_days: int, baseline_days: int):
    max_date = s.index.max()
    recent_start = max_date - pd.Timedelta(days=recent_days - 1)
    baseline_end = recent_start - pd.Timedelta(days=1)
    baseline_start = baseline_end - pd.Timedelta(days=baseline_days - 1)
    recent = s[s.index >= recent_start]
    baseline = s[(s.index >= baseline_start) & (s.index <= baseline_end)]
    return recent, baseline


def drilldown(
    df: pd.DataFrame,
    account_id: str,
    factor: str,
    recent_days: int = 7,
    baseline_days: int = 21,
    level: str = "creative",
) -> pd.DataFrame:
    """下钻：对某个偏离因子，定位到具体素材（或计划）的贡献。

    返回 DataFrame，列：
        {level}_id, {level}_name, baseline, recent, delta, denominator_share, contribution
    其中 contribution ≈ delta × denominator_share，用于排序「谁拖累/抬升最多」。
    """
    acc = df[df["advertiser_id"] == account_id]
    recent, baseline = _windows(acc, recent_days, baseline_days)
    name_map = acc.groupby(f"{level}_id")[f"{level}_name"].first()

    if factor in FACTOR_PARTS:
        num, den = FACTOR_PARTS[factor]
        base_val = _entity_ratio(baseline, level, num, den)
        recent_val = _entity_ratio(recent, level, num, den)
        share = recent.groupby(f"{level}_id")[den].sum() / recent[den].sum()
    elif factor == "结构集中度":
        base_cost = baseline.groupby(f"{level}_id")["stat_cost"].sum()
        recent_cost = recent.groupby(f"{level}_id")["stat_cost"].sum()
        base_val = base_cost / base_cost.sum()          # 基线消耗占比
        recent_val = recent_cost / recent_cost.sum()    # 近期消耗占比
        share = recent_val                              # 权重 = 近期占比
    elif factor == "消耗规模":
        base_val = baseline.groupby(f"{level}_id")["stat_cost"].sum() / baseline_days
        recent_val = recent.groupby(f"{level}_id")["stat_cost"].sum() / recent_days
        share = recent.groupby(f"{level}_id")["stat_cost"].sum() / recent["stat_cost"].sum()
    else:
        raise ValueError(f"未知因子: {factor}")

    out = pd.DataFrame({
        f"{level}_id": base_val.index,
        "baseline": base_val.values,
        "recent": recent_val.reindex(base_val.index).values,
    })
    out[f"{level}_name"] = out[f"{level}_id"].map(name_map)
    out["delta"] = out["recent"] - out["baseline"]
    out["denominator_share"] = share.reindex(base_val.index).values
    out["contribution"] = out["delta"] * out["denominator_share"]
    # 按绝对贡献排序：无论异常是「涨」还是「跌」，元凶都排最前
    out["abs_contribution"] = out["contribution"].abs()
    return out.sort_values("abs_contribution", ascending=False).drop(columns=["abs_contribution"])


def _entity_ratio(df: pd.DataFrame, level: str, num: str, den: str) -> pd.Series:
    """实体级聚合口径：分子求和 / 分母求和。"""
    num_sum = df.groupby(f"{level}_id")[num].sum()
    den_sum = df.groupby(f"{level}_id")[den].sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = num_sum / den_sum
    return r.replace([np.inf, -np.inf], np.nan)
