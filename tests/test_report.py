"""测试 src/llm/report.py：报告生成（大白话 + skill 驱动）。"""
import src.llm.report as report_mod
from src.diagnosis.engine import diagnose


def test_template_report_single_contains_plain_sections(demo_df):
    r = diagnose(demo_df, "A002")
    candidates = r["scores"].head(1)
    text = report_mod._template_report(r, candidates, {})
    assert "【结论】" in text and "【怎么判断的】" in text and "【建议怎么做】" in text
    assert "出价/预算调整" in text


def test_template_report_multiple_lists_multiple_causes(demo_df):
    r = diagnose(demo_df, "A001")
    candidates = r["scores"].head(3)
    text = report_mod._template_report(r, candidates, {})
    assert "结构风险/过度集中" in text
    assert "多个原因" in text


def test_generate_report_falls_back_without_key(demo_df, monkeypatch):
    monkeypatch.setattr(report_mod, "available", lambda: False)
    r = diagnose(demo_df, "A001")
    text = report_mod.generate_report(r, demo_df)
    assert "美妆旗舰店" in text
    assert "【结论】" in text and "【建议怎么做】" in text


def test_evidence_text_uses_plain_language(demo_df):
    r = diagnose(demo_df, "A001")
    text = report_mod._evidence_text(r)
    assert "【数据变化" in text
    assert "广告被点击的比例" in text  # CTR 的大白话解释


def test_skills_text_includes_custom_skills(monkeypatch):
    """自定义 skill 不再按根因过滤，应全部传给 agent。"""
    custom = {
        "name": "我的自定义技能", "root_cause_id": "", "when": "当客单价下降时",
        "tool": "product_price", "tool_description": "查商品",
        "confirm_if": "涨价", "reject_if": "正常",
    }
    monkeypatch.setattr(report_mod, "load_skills", lambda: [custom])
    text = report_mod._skills_text()
    assert "我的自定义技能" in text
    assert "product_price" in text
