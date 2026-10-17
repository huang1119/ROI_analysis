"""黄金集回归入口。

用法：
    python -m scripts.evaluate [--fast] [--dataset roi_golden_set_v1]

- 默认跑完整路径（确定性诊断 + LLM 报告），结果写入 Langfuse（若已配置）
- --fast：跳过 LLM 报告，只跑确定性断言（离线、秒级、可复现）
- --dataset：从 Langfuse Dataset 拉用例跑，而非本地内置黄金集

版本标签见 src/evaluation/version.py（commit + model + skills + tools hash）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.accounts import load_accounts  # noqa: E402
from src.data.synthetic import build_demo_config, generate  # noqa: E402
from src.evaluation.evaluators import (  # noqa: E402
    deviated_stage_match,
    fallback_matches,
    root_cause_match,
    route_matches,
    tool_called,
)
from src.evaluation.golden_set import GOLDEN_ITEMS  # noqa: E402
from src.evaluation.runner import run, run_local  # noqa: E402
from src.evaluation.task import run_task  # noqa: E402
from src.evaluation.version import version_label  # noqa: E402
from src.observability import flush, get_client, shutdown  # noqa: E402
from src.settings import apply_llm_to_env  # noqa: E402

# 离线/确定性断言（--fast 用）：不依赖 agent 运行
DETERMINISTIC_EVALUATORS = [root_cause_match, deviated_stage_match, route_matches, fallback_matches]
# 完整断言：额外验证 agent 的工具调用轨迹
FULL_EVALUATORS = DETERMINISTIC_EVALUATORS + [tool_called]


def _item_input(item):
    return item["input"] if isinstance(item, dict) else item.input


def main() -> None:
    fast = "--fast" in sys.argv
    dataset_name = None
    if "--dataset" in sys.argv:
        dataset_name = sys.argv[sys.argv.index("--dataset") + 1]

    apply_llm_to_env()  # 确保 settings.json 里的 LLM 配置生效（影响 available()）
    cfg = build_demo_config()
    df, _ = generate(cfg)
    accounts = load_accounts()

    def task(*, item, **kwargs):
        return run_task(df, _item_input(item), accounts=accounts, with_report=not fast)

    # 用例来源：本地黄金集 或 Langfuse Dataset
    if dataset_name:
        client = get_client()
        if client is None:
            print("未配置 Langfuse，无法读取数据集")
            sys.exit(1)
        items = list(client.get_dataset(dataset_name).items)
    else:
        items = GOLDEN_ITEMS

    label = version_label()
    print(f"黄金集回归：{len(items)} 条用例" + (f"（数据集 {dataset_name}）" if dataset_name else ""))
    print(f"版本标签：{label}")
    print(f"模式：{'快速（仅确定性断言）' if fast else '完整（含 LLM 报告）'}\n")

    if fast:
        summary = run_local(items, task, DETERMINISTIC_EVALUATORS)
    else:
        summary = run(
            items=items,
            task=task,
            evaluators=FULL_EVALUATORS,
            name="roi-diagnosis",
            run_name=label,
        )

    print(f"run_name: {summary['run_name']}")
    print("通过率：")
    for name, rate in summary["pass_rate"].items():
        print(f"  {name}: {rate:.0%}")
    print()
    for it in summary["per_item"]:
        line = f"  {it['label']}: "
        line += " | ".join(
            f"{e['name']}={e['value']}({e['comment']})" for e in it["evaluations"]
        )
        print(line)

    flush()
    shutdown()


if __name__ == "__main__":
    main()
