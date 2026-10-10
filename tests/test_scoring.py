"""测试 src/diagnosis/scoring.py：赋分制 + 决策层。"""
import math

import numpy as np
import pandas as pd

from src.diagnosis.scoring import _strength, decide, score_root_causes


def _scores(*vals):
    return pd.DataFrame({"name": [f"C{i}" for i in range(len(vals))], "score": list(vals)})


def test_strength_gates_weak_signal():
    assert _strength(0.0) == 0.0
    assert _strength(0.5) == 0.0
    assert _strength(1.0) == 0.0  # |z|<=1 视为噪声


def test_strength_known_values():
    assert abs(_strength(2.0) - (1 - math.exp(-1))) < 1e-9
    assert abs(_strength(6.0) - (1 - math.exp(-5))) < 1e-9


def test_strength_monotonic_and_bounded():
    vals = [_strength(x) for x in np.linspace(0, 10, 200)]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
    assert all(0.0 <= v < 1.0 for v in vals)


def test_score_root_causes_ranks_structure_top():
    """结构集中度↑ + CVR↓ + 消耗规模↑ → RC08（结构风险）应排第一。"""
    evidence = pd.DataFrame({
        "factor": ["CVR", "结构集中度", "消耗规模"],
        "zscore": [-6.0, 5.6, 6.7],
    })
    scores = score_root_causes(evidence)
    assert scores.iloc[0]["id"] == "RC08"
    assert scores.iloc[0]["matched"] == 1


def test_score_root_causes_direction_mismatch_scores_zero():
    """证据方向与根因期望相反 → 不计分。"""
    evidence = pd.DataFrame({"factor": ["CVR"], "zscore": [5.0]})  # CVR 上升，而非下降
    scores = score_root_causes(evidence)
    # RC07 只认 CVR↓，CVR↑ 不应给它加分
    rc07 = scores[scores["id"] == "RC07"].iloc[0]
    assert rc07["score"] == 0.0


def test_decide_single_when_clear_gap():
    assert decide(_scores(3.0, 1.0))["mode"] == "single"


def test_decide_multiple_when_scores_close():
    assert decide(_scores(2.0, 1.5))["mode"] == "multiple"


def test_decide_none_when_below_threshold():
    assert decide(_scores(0.5, 0.4, 0.3))["mode"] == "none"


def test_decide_none_when_empty():
    assert decide(pd.DataFrame({"name": [], "score": []}))["mode"] == "none"


def test_decide_single_row_is_single():
    assert decide(_scores(3.0))["mode"] == "single"
