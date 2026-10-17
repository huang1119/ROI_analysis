"""Code Evaluator（事实核查）：确定性断言，不花钱、可复现（design.md §8.4）。

约定：每条用例的 expected_output 只声明它要断言的字段；未声明的字段，
对应评估器返回「中性通过（跳过）」，不参与该用例的判定。

返回普通 dict {name, value, comment}；Langfuse 实验 runner 会自动归一化，
本地离线 runner 也能直接消费。
"""
from __future__ import annotations

from typing import Any, Optional


def _expected(expected_output: Any, key: str) -> tuple[Any, bool]:
    """返回 (值, 是否声明)。"""
    if isinstance(expected_output, dict) and key in expected_output:
        return expected_output.get(key), True
    return None, False


def _skip(name: str) -> dict:
    return {"name": name, "value": 1, "comment": "未声明该断言（跳过）"}


def root_cause_match(*, output: Any, expected_output: Any = None, **kwargs) -> dict:
    """断言首要根因编码一致（如 RC08）。"""
    want, present = _expected(expected_output, "root_cause")
    if not present:
        return _skip("root_cause_match")
    actual = (output or {}).get("root_cause")
    return {"name": "root_cause_match", "value": 1 if actual == want else 0,
            "comment": f"期望 {want}，实际 {actual}"}


def deviated_stage_match(*, output: Any, expected_output: Any = None, **kwargs) -> dict:
    """断言偏离最显著的漏斗环节一致（如 CVR）。"""
    want, present = _expected(expected_output, "deviated_stage")
    if not present:
        return _skip("deviated_stage_match")
    actual = (output or {}).get("deviated_stage")
    return {"name": "deviated_stage_match", "value": 1 if actual == want else 0,
            "comment": f"期望 {want}，实际 {actual}"}


def route_matches(*, output: Any, expected_output: Any = None, **kwargs) -> dict:
    """断言意图路由结果一致（diagnose/scan/list/chat）。"""
    want, present = _expected(expected_output, "route")
    if not present:
        return _skip("route_matches")
    actual = (output or {}).get("route")
    return {"name": "route_matches", "value": 1 if actual == want else 0,
            "comment": f"期望路由 {want}，实际 {actual}"}


def fallback_matches(*, output: Any, expected_output: Any = None, **kwargs) -> dict:
    """断言兜底类型一致（design.md §8.5）。

    expected_output.fallback_type = None 表示「期望不兜底」；
    = "keyword_miss" 表示「期望命中该兜底」。
    """
    want, present = _expected(expected_output, "fallback_type")
    if not present:
        return _skip("fallback_matches")
    actual = (output or {}).get("fallback_type")
    return {"name": "fallback_matches", "value": 1 if actual == want else 0,
            "comment": f"期望兜底={want}，实际={actual}"}


def tool_called(*, output: Any, expected_output: Any = None, **kwargs) -> dict:
    """断言 agent 调用了期望的工具（design.md §8.4 工具调用轨迹断言）。"""
    want, present = _expected(expected_output, "expected_tool")
    if not present or not want:
        return _skip("tool_called")
    called = [tc.get("name") for tc in (output or {}).get("tool_calls", [])]
    return {"name": "tool_called", "value": 1 if want in called else 0,
            "comment": f"期望调用 {want}，实际调用 {called}"}
