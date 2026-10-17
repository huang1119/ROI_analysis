"""黄金集（v1 起步版，design.md §8.7）。

- 正例来自合成数据的注入异常（ground truth 已知）：
    A001 注入 cvr×0.45 + cost×2.2 → 期望 RC08（结构集中）+ 偏离环节 CVR
    A002 注入 cpm×1.5        → 期望 RC02（出价/预算）+ 偏离环节 展示效率
- 兼底用例：关键词未命中任何意图路由 → 期望 keyword_miss

每条用例的 expected_output 只声明它要断言的字段（其他字段由评估器自动跳过）。
"""
from __future__ import annotations

GOLDEN_ITEMS: list[dict] = [
    {
        "id": "golden-A001",
        "input": {"account_id": "A001"},
        "expected_output": {
            "route": "diagnose",
            "root_cause": "RC08",
            "deviated_stage": "CVR",
            "expected_tool": "cost_share_trend",
            "fallback_type": None,
        },
        "metadata": {
            "scenario": "多因：结构集中(RC08)+CVR下降",
            "injected": "CRT-101 cvr×0.45 + cost×2.2",
        },
    },
    {
        "id": "golden-A002",
        "input": {"account_id": "A002"},
        "expected_output": {
            "route": "diagnose",
            "root_cause": "RC02",
            "deviated_stage": "展示效率",
            "fallback_type": None,
        },
        "metadata": {
            "scenario": "单因：出价/成本上浮(RC02)",
            "injected": "CRT-301 cpm×1.5",
        },
    },
    {
        "id": "golden-chat-fallback",
        "input": {"question": "帮我写一首关于春天的诗"},
        "expected_output": {
            "route": "chat",
            "fallback_type": "keyword_miss",
        },
        "metadata": {
            "scenario": "兼底：关键词未命中任何意图路由，走 LLM 兼底",
            "precondition": "LLM 已配置（否则应为 no_llm_available）",
        },
    },
]
