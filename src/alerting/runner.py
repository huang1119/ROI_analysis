"""扫描 + 推送的统一入口（供 CLI 脚本与内置定时任务共用）。"""
from __future__ import annotations

from datetime import date

from ..data.loader import load_dataframe
from ..llm.report import generate_report
from ..observability import flush, trace
from ..settings import apply_llm_to_env, load_settings
from .scanner import scan_all
from .webhook import push


def run_scan_and_push() -> dict:
    """扫描全部账户，发现异常则生成报告并推送。返回统计。"""
    apply_llm_to_env()
    df = load_dataframe(load_settings())
    results = scan_all(df)

    summary = (f"[ROI 异常扫描] {date.today().isoformat()}："
               f"扫描 {df['advertiser_id'].nunique()} 个账户，发现 {len(results)} 个异常")
    print(summary)
    if results:
        push(summary)
        for r in results:
            with trace("scan.report", input={"account_id": r["account_id"]},
                       metadata={"route": "scan"}) as t:
                report = generate_report(r, df)
                t.update(output={"report": report}, metadata={"account_id": r["account_id"]})
            push("\n" + "=" * 48 + "\n" + report)

    flush()
    return {
        "scanned": int(df["advertiser_id"].nunique()),
        "anomalies": len(results),
    }
