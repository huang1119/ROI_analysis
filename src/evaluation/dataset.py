"""黄金集 ↔ Langfuse Dataset（design.md §8.7）。

- upload_golden_set：把黄金集批量写入 Langfuse Dataset
- convert_trace_to_item：线上 trace → 用例（带 source_trace_id，写行为断言而非逐字话术）
"""
from __future__ import annotations

from typing import Any, Optional

DEFAULT_DATASET = "roi_golden_set_v1"


def _client():
    from ..observability import get_client

    return get_client()


def _ensure_dataset(client, dataset_name: str) -> None:
    """确保数据集存在（幂等）：已存在则跳过，否则创建。"""
    try:
        client.get_dataset(dataset_name)
    except Exception:  # noqa: BLE001
        client.create_dataset(name=dataset_name)

def upload_golden_set(
    items: list[dict],
    *,
    dataset_name: str = DEFAULT_DATASET,
    client=None,
) -> int:
    """把黄金集上传为 Langfuse Dataset，返回写入条数。"""
    client = client or _client()
    if client is None:
        raise RuntimeError("未配置 Langfuse，无法上传数据集")
    _ensure_dataset(client, dataset_name)
    for it in items:
        client.create_dataset_item(
            dataset_name=dataset_name,
            input=it["input"],
            expected_output=it["expected_output"],
            metadata=it.get("metadata"),
            id=it.get("id"),
        )
    return len(items)


def convert_trace_to_item(
    *,
    dataset_name: str = DEFAULT_DATASET,
    trace_id: str,
    input: Any,
    expected_output: Any,
    metadata: Optional[dict] = None,
    client=None,
) -> Any:
    """把一条线上 trace 转成黄金集用例（一键转化，§8.7）。

    期望输出应为「行为断言 + 前置条件」，而不是写死当前版本的话术。
    source_trace_id 关联原始 trace，便于回溯。
    """
    client = client or _client()
    if client is None:
        raise RuntimeError("未配置 Langfuse，无法转化用例")
    _ensure_dataset(client, dataset_name)
    return client.create_dataset_item(
        dataset_name=dataset_name,
        input=input,
        expected_output=expected_output,
        metadata=metadata,
        source_trace_id=trace_id,
    )
