"""测试 src/diagnosis/engine.py：诊断引擎端到端（确定性部分）。"""
from src.diagnosis.engine import diagnose


def test_diagnose_a001_multiple(demo_df):
    r = diagnose(demo_df, "A001")
    assert r["account_name"] == "美妆旗舰店"
    assert r["decision"]["mode"] == "multiple"


def test_diagnose_a002_single(demo_df):
    r = diagnose(demo_df, "A002")
    assert r["account_name"] == "服饰旗舰店"
    assert r["decision"]["mode"] == "single"


def test_diagnose_result_structure(demo_df):
    r = diagnose(demo_df, "A001")
    for key in ["account_id", "account_name", "recent_days", "baseline_days",
                "evidence", "scores", "decision", "drilldowns"]:
        assert key in r


def test_diagnose_evidence_covers_all_factors(demo_df):
    r = diagnose(demo_df, "A001")
    factors = set(r["evidence"]["factor"])
    assert {"展示效率", "CTR", "CVR", "下单率", "客单价", "结构集中度", "消耗规模"} <= factors


def test_diagnose_scores_sorted_desc(demo_df):
    r = diagnose(demo_df, "A001")
    s = r["scores"]["score"].tolist()
    assert s == sorted(s, reverse=True)
