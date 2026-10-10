"""测试 src/web/pdf.py：PDF 生成。"""
from src.web.pdf import generate_report_pdf


def test_generate_pdf_returns_valid_pdf():
    data = generate_report_pdf("# 诊断报告\n\n## 结论\n- 项目1\n**加粗** 正常文字", [])
    assert isinstance(data, bytes)
    assert data[:5] == b"%PDF-"
    assert len(data) > 100


def test_generate_pdf_skips_invalid_images():
    data = generate_report_pdf("# 报告", [{"name": "x.png", "data": ""}])
    assert data[:5] == b"%PDF-"
