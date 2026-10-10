"""测试 src/alerting/scheduler.py：定时调度配置读取。"""
import src.alerting.scheduler as sched


def test_interval_hours_reads_settings(monkeypatch):
    monkeypatch.setattr(sched, "load_settings", lambda: {"alert": {"interval_hours": 24}})
    assert sched._interval_hours() == 24.0


def test_interval_hours_default_zero(monkeypatch):
    monkeypatch.setattr(sched, "load_settings", lambda: {"alert": {}})
    assert sched._interval_hours() == 0.0
