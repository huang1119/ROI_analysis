"""测试 src/data/loader.py：数据源切换。"""
import pandas as pd

from src.data import loader


def test_load_synthetic(demo_df, tmp_path):
    p = tmp_path / "d.parquet"
    demo_df.to_parquet(p)
    settings = {"datasource": {"mode": "合成数据（演示）", "data_file": str(p)}}
    df = loader.load_dataframe(settings)
    assert len(df) == len(demo_df)


def test_load_synthetic_missing_file_raises(tmp_path):
    settings = {"datasource": {"mode": "合成数据（演示）", "data_file": str(tmp_path / "nope.parquet")}}
    import pytest
    with pytest.raises(FileNotFoundError):
        loader.load_dataframe(settings)


def test_load_from_api(monkeypatch):
    fake = pd.DataFrame({"stat_cost": [1.0]})
    monkeypatch.setattr(loader.OceanEngineClient, "fetch_report",
                        lambda self, adv, s, e: fake)
    monkeypatch.setattr(loader, "load_accounts",
                        lambda: [{"advertiser_id": "123", "advertiser_name": "测试"}])
    settings = {"datasource": {"mode": "真实 API", "api": {"access_token": "t"}}}
    df = loader.load_dataframe(settings)
    assert df is fake
