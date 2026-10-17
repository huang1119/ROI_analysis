"""线下测评（黄金集回归）。

task 结构化输出 + Code Evaluator + 黄金集 + 实验 runner。
设计见 design.md §8.7 / §8.8。
"""
from .evaluators import (
    deviated_stage_match,
    fallback_matches,
    root_cause_match,
    route_matches,
    tool_called,
)
from .golden_set import GOLDEN_ITEMS
from .runner import run
from .task import run_chat_task, run_diagnosis_task, run_task, top_deviated_stage, top_root_cause
from .version import compute_version, version_label

__all__ = [
    "GOLDEN_ITEMS",
    "compute_version",
    "deviated_stage_match",
    "fallback_matches",
    "root_cause_match",
    "route_matches",
    "run",
    "run_chat_task",
    "run_diagnosis_task",
    "run_task",
    "tool_called",
    "top_deviated_stage",
    "top_root_cause",
    "version_label",
]
