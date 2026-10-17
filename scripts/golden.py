"""黄金集管理 CLI（design.md §8.7 从信号到评测资产转化）。

用法：
    python -m scripts.golden upload                                   # 上传内置黄金集到 Langfuse
    python -m scripts.golden convert <trace_id> --root-cause RC08 \
        --deviated-stage CVR --precondition "..."                    # 线上 trace 一键转用例

convert 写「行为断言 + 前置条件」，不写死当前版本话术；source_trace_id 关联原始 trace。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evaluation.dataset import DEFAULT_DATASET, convert_trace_to_item, upload_golden_set  # noqa: E402
from src.evaluation.golden_set import GOLDEN_ITEMS  # noqa: E402
from src.observability import flush, get_client, shutdown  # noqa: E402


def _require_client():
    client = get_client()
    if client is None:
        print("未配置 Langfuse（缺 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY）")
        sys.exit(1)
    return client


def cmd_upload(args) -> None:
    client = _require_client()
    n = upload_golden_set(GOLDEN_ITEMS, dataset_name=args.dataset, client=client)
    print(f"已上传 {n} 条用例到数据集「{args.dataset}」")
    flush()
    shutdown()


def cmd_convert(args) -> None:
    client = _require_client()
    trace = client.api.trace.get(args.trace_id)
    if trace is None:
        print(f"未找到 trace：{args.trace_id}")
        sys.exit(1)

    expected = {}
    if args.root_cause:
        expected["root_cause"] = args.root_cause
    if args.deviated_stage:
        expected["deviated_stage"] = args.deviated_stage

    metadata = {"scenario": args.scenario or "线上 trace 转化"}
    if args.precondition:
        metadata["precondition"] = args.precondition
    metadata["source"] = "trace"
    metadata["original_input"] = trace.input

    # 用例 input 用 account_id（可重放）；未提供则回退到 trace 原始 input
    if args.account_id:
        case_input = {"account_id": args.account_id}
    else:
        case_input = trace.input or {"trace_id": args.trace_id}

    item = convert_trace_to_item(
        dataset_name=args.dataset,
        trace_id=args.trace_id,
        input=case_input,
        expected_output=expected,
        metadata=metadata,
        client=client,
    )
    print(f"已转化用例 -> 数据集「{args.dataset}」 item_id={item.id}")
    print(f"  input: {item.input}")
    print(f"  expected: {item.expected_output}")
    print(f"  source_trace: {args.trace_id}")
    flush()
    shutdown()


def main() -> None:
    p = argparse.ArgumentParser(description="黄金集管理")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload", help="上传内置黄金集")
    up.add_argument("--dataset", default=DEFAULT_DATASET)

    cv = sub.add_parser("convert", help="线上 trace 转用例")
    cv.add_argument("trace_id")
    cv.add_argument("--account-id", default="", help="用例 input 的账户 ID（可重放）")
    cv.add_argument("--root-cause")
    cv.add_argument("--deviated-stage")
    cv.add_argument("--precondition", default="", help="前置条件（行为断言语境）")
    cv.add_argument("--scenario", default="")
    cv.add_argument("--dataset", default=DEFAULT_DATASET)

    args = p.parse_args()
    if args.cmd == "upload":
        cmd_upload(args)
    elif args.cmd == "convert":
        cmd_convert(args)


if __name__ == "__main__":
    main()
