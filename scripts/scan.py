"""检测告警脚本：扫描全部账户，发现 ROI 异常则生成报告并推送。

用法：
    python -m scripts.scan

也可由 Web 应用内置定时器自动执行（见「配置 → 告警」的扫描间隔）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.alerting.runner import run_scan_and_push  # noqa: E402


def main() -> None:
    result = run_scan_and_push()
    print(f"完成：扫描 {result['scanned']} 个账户，发现 {result['anomalies']} 个异常")


if __name__ == "__main__":
    main()
