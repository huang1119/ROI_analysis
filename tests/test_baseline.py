"""测试 src/diagnosis/baseline.py：证据层。"""
import numpy as np
import pandas as pd
import pytest

from src.diagnosis.baseline import (
    _ratio,
    detect_account_factors,
    drilldown,
    robust_zscore,
)


def test_robust_zscore_known_value():
    z = robust_zscore(np.array([9.0, 10.0, 11.0]), np.array([4.0, 5.0, 6.0]))
    assert round(z, 2) == 3.37


def test_robust_zscore_no_deviation_is_zero():
    assert robust_zscore(np.array([5.0, 5.0]), np.array([5.0, 5.0])) == 0.0


def test_robust_zscore_direction_sign():
    # 近期中位数高于基线 → z > 0；低于 → z < 0
    assert robust_zscore(np.array([10.0]), np.array([5.0, 6.0])) > 0
    assert robust_zscore(np.array([2.0]), np.array([5.0, 6.0])) < 0


def test_ratio_division_by_zero_yields_nan():
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [0.0, 0.0]})
    r = _ratio(df, "a", "b")
    assert r.isna().all()


def test_detect_account_factors_finds_injected_anomalies(demo_df):
    ev = detect_account_factors(demo_df, "A001")
    z = dict(zip(ev["factor"], ev["zscore"]))
    assert z["CVR"] < -5            # 注入 CVR×0.45
    assert z["结构集中度"] > 5       # 注入 cost×2.2 → 占比冲高
    assert z["消耗规模"] > 5         # 总消耗同步上升
    assert abs(z["CTR"]) < 2        # CTR 未被扰动，应接近 0


def test_detect_account_factors_columns(demo_df):
    ev = detect_account_factors(demo_df, "A001")
    assert set(ev.columns) == {"factor", "baseline_med", "recent_med", "zscore", "pct_change", "direction"}
    assert set(ev["factor"]) == {"展示效率", "CTR", "CVR", "下单率", "客单价", "结构集中度", "消耗规模"}


def test_drilldown_cvr_locks_culprit(demo_df):
    dd = drilldown(demo_df, "A001", "CVR")
    assert dd.iloc[0]["creative_id"] == "CRT-101"
    assert dd.iloc[0]["recent"] < dd.iloc[0]["baseline"]


def test_drilldown_structure_share(demo_df):
    dd = drilldown(demo_df, "A001", "结构集中度")
    top = dd.iloc[0]
    assert top["creative_id"] == "CRT-101"
    assert top["recent"] > top["baseline"]  # 占比上升


def test_drilldown_unknown_factor_raises(demo_df):
    with pytest.raises(ValueError):
        drilldown(demo_df, "A001", "不存在的因子")
