"""端到端演示：对合成数据运行确定性诊断引擎（证据层+推理层+决策层）。

用法：
    python -m scripts.diagnose_demo [account_id ...]
不传参数则诊断全部账户。
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnosis.engine import diagnose  # noqa: E402


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def print_report(result: dict) -> None:
    print("=" * 72)
    print(f"账户：{result['account_name']} ({result['account_id']})")
    print(f"窗口：近 {result['recent_days']} 天 vs 前 {result['baseline_days']} 天基线")
    print("-" * 72)

    print("\n[证据层] 各因子偏离（z-score，|z|>2 视为显著）：")
    ev = result["evidence"].copy()
    ev["zscore"] = ev["zscore"].round(2)
    ev["pct_change"] = ev["pct_change"].map(_fmt_pct)
    print(ev[["factor", "baseline_med", "recent_med", "zscore", "pct_change", "direction"]].to_string(index=False))

    print("\n[推理层] 根因打分排序：")
    sc = result["scores"].copy()
    sc["score"] = sc["score"].round(2)
    print(sc.to_string(index=False))

    mode = result["decision"]["mode"]
    mode_cn = {"single": "单因（可直接下结论）", "multiple": "多因（需升级 LLM 补充数据深挖）", "none": "无明显异常"}[mode]
    print(f"\n[决策层] {mode_cn}")

    print("\n[下钻] 偏离最显著因子的素材级贡献：")
    for factor, dd in result["drilldowns"].items():
        if dd is None or dd.empty:
            continue
        print(f"  ◆ {factor}")
        show = dd.head(3).copy()
        show["baseline"] = show["baseline"].round(4)
        show["recent"] = show["recent"].round(4)
        show["delta"] = show["delta"].round(4)
        show["denominator_share"] = show["denominator_share"].round(3)
        show["contribution"] = show["contribution"].round(4)
        print(show.to_string(index=False))
        print()
    print("=" * 72, "\n")


def main() -> None:
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "synthetic_daily.parquet")
    df = pd.read_parquet(data_path)

    account_ids = sys.argv[1:] or sorted(df["advertiser_id"].unique())
    for aid in account_ids:
        print_report(diagnose(df, aid))


if __name__ == "__main__":
    main()
