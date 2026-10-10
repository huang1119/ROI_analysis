"""测试 src/llm/supplementary.py：补充数据获取器。"""
from src.diagnosis.engine import diagnose
from src.llm.supplementary import (
    cost_share_trend,
    creative_ctr_trend,
    fetch_supplementary,
)


def test_fetch_supplementary_returns_subset_of_top_causes(demo_df):
    r = diagnose(demo_df, "A001")
    top = r["scores"].head(3)["id"].tolist()
    sup = fetch_supplementary(demo_df, "A001", top, r["drilldowns"])
    assert set(sup) <= set(top)
    assert len(sup) > 0


def test_fetch_supplementary_includes_rc08_structure(demo_df):
    r = diagnose(demo_df, "A001")
    top = r["scores"].head(3)["id"].tolist()
    sup = fetch_supplementary(demo_df, "A001", top, r["drilldowns"])
    assert "RC08" in sup
    assert "判定" in sup["RC08"]


def test_creative_ctr_trend_returns_verdict(demo_df):
    d = creative_ctr_trend(demo_df, "CRT-101")
    assert "判定" in d and "变化" in d


def test_cost_share_trend_detects_rise(demo_df):
    """CRT-101 注入 cost×2.2 → 近 30 天后半段占比应高于前半段。"""
    d = cost_share_trend(demo_df, "A001", "CRT-101")
    assert "上升" in d["判定"]
