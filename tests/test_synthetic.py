"""测试 src/data/synthetic.py：合成数据生成器。"""
import pandas as pd

from src.data.schema import DIM_COLS, METRIC_COLS
from src.data.synthetic import build_demo_config, generate


def test_generate_row_and_shape(demo_df):
    assert list(demo_df.columns) == DIM_COLS + METRIC_COLS
    # 每素材每天一行，无重复
    assert len(demo_df) == demo_df[["creative_id", "date"]].drop_duplicates().shape[0]
    assert demo_df["creative_id"].nunique() == 6
    assert demo_df["date"].nunique() == 60


def test_generate_is_deterministic():
    cfg = build_demo_config()
    d1, _ = generate(cfg)
    d2, _ = generate(cfg)
    pd.testing.assert_frame_equal(d1, d2)


def test_funnel_is_monotonic(demo_df):
    """点击率/转化率/下单率均 <1，故漏斗逐级递减。"""
    assert (demo_df["show_cnt"] >= demo_df["click_cnt"]).all()
    assert (demo_df["click_cnt"] >= demo_df["convert_cnt"]).all()
    assert (demo_df["convert_cnt"] >= demo_df["pay_order_count"]).all()


def test_metrics_nonnegative(demo_df):
    assert (demo_df["stat_cost"] > 0).all()
    assert (demo_df["pay_amount"] >= 0).all()


def test_injected_cvr_drop_reflected(demo_df):
    """CRT-101 注入 CVR×0.45：末 7 天 CVR 中位数应显著低于首 7 天。"""
    c = demo_df[demo_df["creative_id"] == "CRT-101"].copy()
    c["cvr"] = c["convert_cnt"] / c["click_cnt"]
    c["day"] = (c["date"] - c["date"].min()).dt.days
    first = c[c["day"] <= 6]["cvr"].median()
    last = c[c["day"] >= 53]["cvr"].median()
    assert last < first * 0.6


def test_injected_cost_spike_reflected(demo_df):
    """CRT-101 注入 cost×2.2：末 7 天日消耗中位数应显著高于首 7 天。"""
    c = demo_df[demo_df["creative_id"] == "CRT-101"].copy()
    c["day"] = (c["date"] - c["date"].min()).dt.days
    first = c[c["day"] <= 6]["stat_cost"].median()
    last = c[c["day"] >= 53]["stat_cost"].median()
    assert last > first * 1.5


def test_anomaly_log_records_ground_truth(demo_log):
    assert list(demo_log["factor"]) == ["cvr", "cost", "cpm"]
    assert set(demo_log["creative_id"]) == {"CRT-101", "CRT-301"}
