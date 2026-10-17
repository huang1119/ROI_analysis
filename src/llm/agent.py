"""Agent 工具调用循环。

LLM 依据【技能库】中每个 skill 的 "when"（什么情况），自主决定调哪些工具取证，
逐轮调用 → 拿到结果 → 再判断是否还需补查，最终给出结论。

execute: 签名 (tool_name, args_dict) -> dict，由调用方注入（绑定数据上下文）。
"""
from __future__ import annotations

import json

from ..observability import record_fallback, record_tool_call, span
from .client import chat, chat_raw


def run_agent(
    system: str,
    user_context: str,
    tools: list[dict],
    execute,
    max_rounds: int = 4,
) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_context},
    ]

    for _ in range(max_rounds):
        msg = chat_raw(messages, tools=tools)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return msg.get("content") or ""

        messages.append(msg)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            with span(f"tool:{name}", input={"name": name, "arguments": args}, as_type="tool") as s:
                try:
                    result = execute(name, args)
                    is_error = isinstance(result, dict) and "error" in result
                    status = "error" if is_error else "ok"
                    record_tool_call(name, args, result, status)
                    s.update(
                        output=result,
                        metadata={"tool": name, "status": status},
                        level="ERROR" if is_error else None,
                        status_message=str(result.get("error")) if is_error else None,
                    )
                except Exception as e:  # noqa: BLE001
                    result = {"error": str(e)}
                    record_tool_call(name, args, result, "error")
                    s.update(
                        output=result,
                        metadata={"tool": name, "status": "error"},
                        level="ERROR",
                        status_message=str(e),
                    )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    # 达到最大轮次仍未给出结论，强制要求总结（显式兜底分支）
    record_fallback("deterministic_fallback")
    messages.append({
        "role": "user",
        "content": "请基于以上查证结果，直接给出最终诊断报告，不要再调用工具。",
    })
    return chat(messages)
