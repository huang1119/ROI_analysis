"""测试 Web 后端的意图识别、序列化与导出。"""
import os

import src.web.app as web_app
from src.diagnosis.engine import diagnose
from src.web.app import find_account


def test_find_account_by_name(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    assert find_account("为什么美妆旗舰店的ROI下降了") == "A001"


def test_find_account_by_id(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A002", "advertiser_name": "服饰旗舰店"}])
    assert find_account("A002 怎么了") == "A002"


def test_find_account_not_found(monkeypatch):
    monkeypatch.setattr(web_app, "load_accounts",
                        lambda: [{"advertiser_id": "A001", "advertiser_name": "美妆旗舰店"}])
    assert find_account("今天天气怎么样") is None


def test_serialize_result_has_structured_fields(demo_df, monkeypatch):
    monkeypatch.setattr(web_app, "generate_report", lambda r, df: "报告")
    r = diagnose(demo_df, "A001")
    s = web_app.serialize_result(r, demo_df)
    assert s["report"] == "报告"
    assert s["decision"] == "multiple"
    assert "evidence" in s and "scores" in s and "drilldowns" in s


def test_export_report_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "load_settings", lambda: {"export": {"dir": str(tmp_path)}})
    r = web_app.export_report(web_app.ExportIn(filename="test.md", content="# 报告"))
    assert r["ok"] is True
    assert (tmp_path / "test.md").read_text(encoding="utf-8") == "# 报告"


def test_export_report_sanitizes_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "load_settings", lambda: {"export": {"dir": str(tmp_path)}})
    r = web_app.export_report(web_app.ExportIn(filename="../evil:path", content="x"))
    assert os.path.dirname(r["path"]) == str(tmp_path)  # 不能逃逸出导出目录
    assert os.path.basename(r["path"]).endswith(".md")
