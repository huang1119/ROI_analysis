"""测试 src/data/oceanengine.py：千川 API 客户端（不发起真实请求）。"""
import pandas as pd
import pytest

from src.data.oceanengine import METRICS_MAP, OceanEngineClient, OceanEngineError


def test_metrics_map_covers_unified_columns():
    from src.data.schema import METRIC_COLS
    assert set(METRICS_MAP.values()) == set(METRIC_COLS)


def test_check_raises_on_api_error():
    with pytest.raises(OceanEngineError):
        OceanEngineClient._check({"code": 40001, "message": "token 无效"})


def test_check_passes_on_code_zero():
    OceanEngineClient._check({"code": 0, "message": "OK"})


def test_test_connection_without_token():
    ok, msg = OceanEngineClient().test_connection()
    assert ok is False
    assert "token" in msg


def test_fetch_report_requires_advertiser_ids():
    c = OceanEngineClient(access_token="t")
    with pytest.raises(OceanEngineError, match="广告主"):
        c.fetch_report([], "2024-01-01", "2024-01-07")


def test_to_dataframe_maps_metrics():
    c = OceanEngineClient(access_token="t")
    rows = [{
        "dimensions": {"stat_datetime": "2024-01-01", "advertiser_id": "A1", "creative_id": "C1"},
        "metrics": {
            "stat_cost": 100, "show_cnt": 1000, "click_cnt": 50,
            "convert_cnt": 5, "stat_pay_amount": 500, "pay_order_count": 3,
        },
    }]
    df = c._to_dataframe(rows)
    assert isinstance(df, pd.DataFrame)
    assert df.iloc[0]["stat_cost"] == 100
    assert df.iloc[0]["pay_amount"] == 500
    assert df.iloc[0]["pay_order_count"] == 3
    assert df.iloc[0]["creative_id"] == "C1"
