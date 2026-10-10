"""PDF 报告生成（reportlab）：支持中文 + 嵌入图表图片。"""
from __future__ import annotations

import base64
import html
import io
import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

# 注册中文字体（Windows 黑体，退化为 Helvetica）
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
]
_FONT = "Helvetica"
for _p in _FONT_CANDIDATES:
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont("Chinese", _p))
            _FONT = "Chinese"
            break
        except Exception:  # noqa: BLE001
            continue


def _styles() -> dict[str, ParagraphStyle]:
    def mk(name, size, **kw):
        kw.setdefault("fontName", _FONT)
        kw.setdefault("leading", size * 1.5)
        kw.setdefault("spaceAfter", 4)
        return ParagraphStyle(name, fontSize=size, **kw)

    return {
        "title": mk("Title", 16, fontName=_FONT, spaceAfter=8),
        "h1": mk("H1", 14, spaceBefore=6),
        "h2": mk("H2", 12, spaceBefore=4),
        "body": mk("Body", 10.5),
        "bullet": mk("Bullet", 10.5, leftIndent=12, spaceAfter=2),
    }


def _inline(text: str) -> str:
    """转义 HTML 并把 **bold** 转成 <b>。"""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def generate_report_pdf(report_text: str, images: list[dict] | None = None) -> bytes:
    """把 Markdown 报告 + 图表图片渲染成 PDF 字节流。"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, margins=18 * mm)
    story = []
    st = _styles()

    for line in report_text.splitlines():
        line = line.rstrip()
        if not line.strip():
            story.append(Spacer(1, 2 * mm))
            continue
        stripped = line.lstrip()
        if line.startswith("### "):
            story.append(Paragraph(_inline(line[4:]), st["h2"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline(line[3:]), st["h1"]))
        elif line.startswith("# "):
            story.append(Paragraph(_inline(line[2:]), st["title"]))
        elif stripped.startswith("- "):
            story.append(Paragraph("• " + _inline(stripped[2:]), st["bullet"]))
        elif re.match(r"^\d+\.\s", stripped):
            story.append(Paragraph(_inline(stripped), st["bullet"]))
        elif stripped == "---" or stripped == "***":
            story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), thickness=0.5))
        else:
            story.append(Paragraph(_inline(line), st["body"]))

    # 嵌入图表
    if images:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("图表", st["h1"]))
        for img in images:
            data = img.get("data") if isinstance(img, dict) else None
            if not data:
                continue
            try:
                raw = base64.b64decode(data)
            except Exception:  # noqa: BLE001
                continue
            story.append(Image(io.BytesIO(raw), width=174 * mm, height=88 * mm))
            story.append(Spacer(1, 4 * mm))

    doc.build(story)
    return buf.getvalue()
