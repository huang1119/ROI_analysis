"""测试 src/diagnosis/root_causes.py：根因库结构完整性。"""
from src.diagnosis.baseline import FUNNEL_FACTORS
from src.diagnosis.root_causes import ROOT_CAUSES, ROOT_CAUSE_BY_ID

VALID_FACTORS = set(FUNNEL_FACTORS) | {"结构集中度", "消耗规模"}


def test_ids_unique_and_complete():
    ids = [rc.id for rc in ROOT_CAUSES]
    assert len(ids) == len(set(ids)) == 8
    assert set(ROOT_CAUSE_BY_ID) == set(ids)


def test_each_cause_has_required_fields():
    for rc in ROOT_CAUSES:
        assert rc.name and rc.description and rc.extra_data and rc.suggestion


def test_evidence_patterns_valid():
    for rc in ROOT_CAUSES:
        for pat in rc.evidence:
            assert pat.factor in VALID_FACTORS, f"{rc.id} 引用未知因子 {pat.factor}"
            assert pat.direction in ("up", "down")
            assert pat.weight > 0


def test_no_duplicate_evidence_factor_within_cause():
    for rc in ROOT_CAUSES:
        factors = [p.factor for p in rc.evidence]
        assert len(factors) == len(set(factors)), f"{rc.id} 重复引用同一因子"
