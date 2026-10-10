"""内置定时扫描调度器（APScheduler）。

Web 应用运行时，按「配置 → 告警」里的扫描间隔定时扫描 + 推送。
修改间隔后调用 reschedule() 立即生效。注意：仅在 Web 应用运行期间生效。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..settings import load_settings

JOB_ID = "roi_scan"
_scheduler: BackgroundScheduler | None = None


def _interval_hours() -> float:
    return float(load_settings().get("alert", {}).get("interval_hours", 0) or 0)


def _job() -> None:
    from .runner import run_scan_and_push

    try:
        run_scan_and_push()
    except Exception as e:  # noqa: BLE001
        print(f"[定时扫描失败] {e}")


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.start()
    reschedule()


def reschedule() -> None:
    global _scheduler
    if _scheduler is None:
        return
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)
    hours = _interval_hours()
    if hours > 0:
        _scheduler.add_job(_job, IntervalTrigger(hours=hours), id=JOB_ID, replace_existing=True)
        print(f"[定时扫描] 已启用：每 {hours:g} 小时扫描一次", flush=True)
    else:
        print("[定时扫描] 已关闭", flush=True)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
