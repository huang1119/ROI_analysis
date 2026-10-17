"""可观测性埋点（Langfuse 接入）。

未配置 Langfuse 凭据时，所有埋点函数退化为 no-op，不影响业务与测试。
设计见 design.md §8（测评模块）。
"""
from .client import (
    flush,
    generation,
    get_client,
    get_config,
    hash_account_id,
    is_configured,
    is_enabled,
    record_fallback,
    record_tool_call,
    record_topic,
    redact_text,
    sanitize,
    shutdown,
    span,
    start_recording,
    stop_recording,
    trace,
)

__all__ = [
    "flush",
    "generation",
    "get_client",
    "get_config",
    "hash_account_id",
    "is_configured",
    "is_enabled",
    "record_fallback",
    "record_tool_call",
    "record_topic",
    "redact_text",
    "sanitize",
    "shutdown",
    "span",
    "start_recording",
    "stop_recording",
    "trace",
]
