"""一键重放：重新生成 Langfuse 里的全部验收数据。

依次执行：
  1. scripts.ask      → 生成 1 条对话诊断 trace（Traces 里看）
  2. scripts.evaluate → 跑黄金集回归，生成 1 次实验（Experiments 里看）
  3. scripts.golden upload → 上传/刷新黄金集（Datasets 里看，幂等）

用法：
    python -m scripts.replay
"""
from __future__ import annotations

import subprocess
import sys

STEPS = [
    ("生成诊断 trace", ["scripts.ask", "为什么美妆旗舰店的ROI下降了"]),
    ("跑黄金集回归实验", ["scripts.evaluate"]),
    ("上传黄金集数据集", ["scripts.golden", "upload"]),
]


def main() -> None:
    for title, args in STEPS:
        print("=" * 64)
        print(f"[{title}]  python -m {' '.join(args)}")
        print("=" * 64)
        r = subprocess.run([sys.executable, "-m", *args])
        if r.returncode != 0:
            print(f"\n✗ 失败（exit {r.returncode}），终止")
            sys.exit(r.returncode)
        print()

    print("全部完成。去 Langfuse UI 依次看：")
    print("  · Traces（追踪）    → cli.ask 的完整链路")
    print("  · Experiments（实验）→ 最新一次黄金集跑批（4 项评分）")
    print("  · Datasets（数据集）→ roi_golden_set_v1 用例")


if __name__ == "__main__":
    main()
