"""推理层：赋分制打分 + 决策层（单因 / 多因 / 无异常）。"""
from __future__ import annotations

import math

import pandas as pd

from .root_causes import ROOT_CAUSES


def _strength(z: float) -> float:
    """把 |z| 映射到 [0,1)。|z|<=1 视为噪声不计分；之后 1-exp(-(|z|-1))。

    例：|z|=1→0，|z|=2→0.63，|z|=6→0.99。拉开「轻微波动」与「显著偏离」的差距。
    """
    a = abs(z)
    if a <= 1.0:
        return 0.0
    return 1.0 - math.exp(-(a - 1.0))


def score_root_causes(evidence: pd.DataFrame) -> pd.DataFrame:
    """把证据映射到根因库逐条打分。

    证据 direction 与根因期望方向一致才计分；score = Σ(weight × strength(|z|))。
    返回按 score 降序的 DataFrame：id, name, score, matched。
    """
    zmap = dict(zip(evidence["factor"], evidence["zscore"]))

    rows = []
    for rc in ROOT_CAUSES:
        if not rc.evidence:  # 无证据模式的（如大促效应）不参与赋分，交给补充数据层
            continue
        total, matched = 0.0, 0
        for pat in rc.evidence:
            z = zmap.get(pat.factor)
            if z is None:
                continue
            hit = (pat.direction == "up" and z > 0) or (pat.direction == "down" and z < 0)
            if hit:
                total += pat.weight * _strength(z)
                matched += 1
        rows.append({"id": rc.id, "name": rc.name, "score": total, "matched": matched})

    out = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    return out


def decide(
    scores: pd.DataFrame,
    ratio_threshold: float = 1.5,
    min_score: float = 0.8,
) -> dict:
    """决策层：悬殊→单因直答；接近→多因（升级 LLM 深挖）；过低→无明显异常。

    阈值说明（MVP 初值，可调）：
      - top1.score < min_score         → 无显著异常
      - top1.score >= ratio × top2.score → 单因
      - 否则                           → 多因
    """
    if scores.empty or scores.iloc[0]["score"] < min_score:
        return {"mode": "none", "top": scores}

    top1 = scores.iloc[0]
    if len(scores) == 1:
        return {"mode": "single", "top": scores}

    top2 = scores.iloc[1]
    if top2["score"] == 0 or top1["score"] >= ratio_threshold * top2["score"]:
        return {"mode": "single", "top": scores}
    return {"mode": "multiple", "top": scores}
