"""测试 src/data/schema.py：漏斗分解口径。"""
import numpy as np

from src.data.schema import DIM_COLS, FACTOR_COLUMN, FUNNEL_FACTORS, METRIC_COLS, compute_funnel


def test_compute_funnel_roas_telescopes(demo_df):
    """核心不变量：ROAS = 展示效率 × CTR × CVR × 下单率 × 客单价（精确恒等）。"""
    f = compute_funnel(demo_df)
    rhs = f["imp_eff"] * f["ctr"] * f["cvr"] * f["order_rate"] * f["aov"]
    assert np.allclose(f["roas"], rhs, rtol=1e-6, equal_nan=True)


def test_compute_funnel_cpm_is_inverse_of_imp_eff(demo_df):
    f = compute_funnel(demo_df)
    assert np.allclose(f["cpm"] * f["imp_eff"], 1000.0, rtol=1e-6)


def test_compute_funnel_adds_all_derived_columns(demo_df):
    f = compute_funnel(demo_df)
    for col in ["imp_eff", "ctr", "cvr", "order_rate", "aov", "roas", "cpm"]:
        assert col in f.columns


def test_funnel_factor_maps_to_columns():
    """五个漏斗环节一一对应派生列。"""
    assert set(FACTOR_COLUMN) == set(FUNNEL_FACTORS)
    assert len(FACTOR_COLUMN) == 5


def test_schema_column_contract():
    assert len(DIM_COLS) == 7
    assert METRIC_COLS == [
        "stat_cost", "show_cnt", "click_cnt", "convert_cnt",
        "pay_order_count", "pay_amount",
    ]
