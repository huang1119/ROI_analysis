"""测试 src/alerting/scanner.py：检测层扫描。"""
from src.alerting.scanner import scan_all
from src.data.synthetic import (
    AdvertiserSpec,
    CampaignSpec,
    CreativeSpec,
    SyntheticConfig,
    generate,
)


def test_scan_all_finds_demo_anomalies(demo_df):
    results = scan_all(demo_df)
    assert len(results) == 2
    assert all(r["decision"]["mode"] != "none" for r in results)
    assert {r["account_id"] for r in results} == {"A001", "A002"}


def test_scan_all_returns_empty_when_clean():
    """无异常、无噪声的平坦数据 → 扫描结果应为空。"""
    cfg = SyntheticConfig(
        advertisers=[AdvertiserSpec("T001", "测试账户", [
            CampaignSpec("C1", "计划", [CreativeSpec(
                "CR1", "素材", cpm=40, ctr=0.03, cvr=0.05,
                order_rate=0.3, aov=150, daily_cost=1000,
            )]),
        ])],
        anomalies=[],
        days=30,
        seed=1,
        noise_cost=0, noise_cpm=0, noise_ctr=0, noise_cvr=0,
        noise_order_rate=0, noise_aov=0,
        trend_cost=0, trend_cpm=0, trend_ctr=0,
        weekend_cost=1.0, weekend_ctr=1.0,
    )
    data, _ = generate(cfg)
    assert scan_all(data) == []
