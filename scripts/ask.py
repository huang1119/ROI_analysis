"""CLI 对话入口：问一句，agent 查数据 → 诊断 → 输出报告。

用法：
    python -m scripts.ask "为什么美妆旗舰店的 ROI 下降了"
    python -m scripts.ask "A002 怎么了"

账户名/ID 从问题文本中匹配；未匹配到则列出可用账户。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from src.diagnosis.engine import diagnose  # noqa: E402
from src.llm.report import generate_report  # noqa: E402


def find_account(df: pd.DataFrame, question: str) -> str | None:
    accounts = df[["advertiser_id", "advertiser_name"]].drop_duplicates()
    q = question.lower()
    for _, row in accounts.iterrows():
        if row["advertiser_id"].lower() in q or row["advertiser_name"].lower() in q:
            return row["advertiser_id"]
    # 允许纯数字 ID 或简短别名（如 "A001"）
    for _, row in accounts.iterrows():
        if row["advertiser_id"] in question:
            return row["advertiser_id"]
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python -m scripts.ask \"为什么美妆旗舰店的 ROI 下降了\"")
        return

    question = sys.argv[1]
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "synthetic_daily.parquet")
    df = pd.read_parquet(data_path)

    account_id = find_account(df, question)
    if account_id is None:
        accounts = df[["advertiser_id", "advertiser_name"]].drop_duplicates()
        print("未识别到账户，可用账户：")
        print(accounts.to_string(index=False))
        return

    print(f"正在诊断：{question}\n")
    result = diagnose(df, account_id)
    report = generate_report(result, df)
    print(report)


if __name__ == "__main__":
    main()
