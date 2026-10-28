"""PDF report (ReportLab) with Noto fonts for Devanagari and Kannada.

Note: ReportLab draws glyphs without complex-script shaping, so Devanagari and Kannada
conjuncts may render in their unshaped form. The original transcript text is still
preserved exactly in the database and the API.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DISCLAIMER = "Investigative aid only. Not an identification."
CLOUD_FOOTNOTE = (
    "Generated with cloud AI providers (Google Gemini, Groq, Cloudflare Workers AI) in demo mode."
)
MOCK_FOOTNOTE = "Generated fully offline with mock providers."

_FONTS = {
    "NotoSans": "NotoSans-Regular.ttf",
    "NotoSansDevanagari": "NotoSansDevanagari-Regular.ttf",
    "NotoSansKannada": "NotoSansKannada-Regular.ttf",
}
_registered: dict[str, str] = {}


def register_fonts(font_dir: Path) -> dict[str, str]:
    """Register available Noto fonts; map logical name -> registered font (or Helvetica)."""
    if _registered:
        return _registered
    for name, fname in _FONTS.items():
        p = font_dir / fname
        try:
            if p.exists():
                pdfmetrics.registerFont(TTFont(name, str(p)))
                _registered[name] = name
            else:
                _registered[name] = "Helvetica"
        except Exception:  # noqa: BLE001
            _registered[name] = "Helvetica"
    return _registered


def font_for_language(lang: str) -> str:
    return {
        "hi": _registered.get("NotoSansDevanagari", "Helvetica"),
        "kn": _registered.get("NotoSansKannada", "Helvetica"),
    }.get(lang, _registered.get("NotoSans", "Helvetica"))


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def build_report(
    *,
    font_dir: Path,
    case: dict[str, Any],
    officer: dict[str, Any],
    session: dict[str, Any],
    witness: dict[str, Any],
    sketch_png: bytes | None,
    confidences: dict[str, str],
    locks: dict[str, dict[str, Any]],
    feature_sheet: dict[str, Any],
    statements: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    versions: list[dict[str, Any]],
    display_event_count: int,
    export_hashes: list[dict[str, str]],
    cloud_used: bool,
    generated_at: datetime,
) -> bytes:
    fonts = register_fonts(font_dir)
    base_font = fonts.get("NotoSans", "Helvetica")
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontName=base_font,
        fontSize=9.5,
        leading=13,
        alignment=TA_LEFT,
    )
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=colors.grey)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=base_font, fontSize=16)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=base_font, fontSize=12)
    local_style = ParagraphStyle(
        "local",
        parent=body,
        fontName=font_for_language(witness.get("preferred_language", "en")),
        fontSize=10.5,
        leading=15,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Nishaan report {case.get('case_number', '')}",
    )
    story: list[Any] = []
    story.append(_p("Nishaan - Suspect sketch report", h1))
    story.append(_p(DISCLAIMER, small))
    story.append(Spacer(1, 4 * mm))
    meta = [
        ["Case number", case.get("case_number", "")],
        ["Station", case.get("station", "")],
        ["Crime type", case.get("crime_type", "")],
        ["Officer", f"{officer.get('full_name', '')} ({officer.get('username', '')})"],
        ["Session", session.get("id", "")],
        ["Witness", f"{witness.get('display_name', '')} [{witness.get('preferred_language', '')}]"],
        ["Report generated", generated_at.strftime("%Y-%m-%d %H:%M UTC")],
        ["Images shown to witness", str(display_event_count)],
    ]
    t = Table([[_p(a, body), _p(str(b), body)] for a, b in meta], colWidths=[45 * mm, 120 * mm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    if sketch_png:
        story.append(_p("Final sketch", h2))
        story.append(Image(io.BytesIO(sketch_png), width=90 * mm, height=90 * mm))
        story.append(Spacer(1, 3 * mm))

    story.append(_p("Witness confidence per feature", h2))
    rows = [["Feature", "Confidence", "Locked"]]
    features = sorted(set(confidences) | set(locks))
    for f in features:
        conf = confidences.get(f) or (locks.get(f) or {}).get("confidence") or "-"
        rows.append([f, conf, "yes" if (locks.get(f) or {}).get("locked") else "no"])
    if len(rows) == 1:
        rows.append(["-", "-", "-"])
    t = Table([[_p(c, body) for c in r] for r in rows], colWidths=[60 * mm, 50 * mm, 30 * mm])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 5 * mm))

    story.append(_p("Feature sheet", h2))
    rows = [["Field", "Value", "Confidence", "Source text"]]
    for key, entry in sorted(feature_sheet.items()):
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        rows.append(
            [
                key,
                str(entry.get("value", "")),
                str(entry.get("confidence", "")),
                str(entry.get("source_text", ""))[:120],
            ]
        )
    if len(rows) == 1:
        rows.append(["-", "-", "-", "-"])
    t = Table(
        [[_p(c, body) for c in r] for r in rows], colWidths=[32 * mm, 45 * mm, 24 * mm, 64 * mm]
    )
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    story.append(_p("Free-recall statement", h2))
    for st in statements:
        story.append(
            _p(
                f"[{st.get('kind')}] {st.get('created_at', '')} via {st.get('source')} "
                f"({st.get('language')})",
                small,
            )
        )
        story.append(
            Paragraph(
                escape(st.get("original", "")).replace("\n", "<br/>"),
                ParagraphStyle(
                    "st_local",
                    parent=local_style,
                    fontName=font_for_language(st.get("language", "en")),
                ),
            )
        )
        if st.get("english") and st.get("language") != "en":
            story.append(_p("English: " + st.get("english", ""), body))
        story.append(Spacer(1, 3 * mm))

    story.append(_p("Interview questions and answers", h2))
    for i, q in enumerate(questions, start=1):
        story.append(_p(f"Q{i} [{q.get('field_key')}] {q.get('text_en', '')}", body))
        if q.get("text_local") and q.get("text_local") != q.get("text_en"):
            story.append(Paragraph(escape(q.get("text_local", "")), local_style))
        ans = q.get("answer") or "-"
        story.append(_p(f"A: {ans}", body))
        story.append(Spacer(1, 2 * mm))

    story.append(_p("Version history", h2))
    rows = [["#", "Created", "Source", "Edit", "Provider", "Rating"]]
    for i, v in enumerate(versions, start=1):
        rows.append(
            [
                str(i),
                str(v.get("created_at", ""))[:19],
                v.get("edit_source", ""),
                str(v.get("summary", ""))[:60],
                v.get("provider", ""),
                v.get("rating") or "-",
            ]
        )
    t = Table(
        [[_p(str(c), small) for c in r] for r in rows],
        colWidths=[8 * mm, 32 * mm, 20 * mm, 60 * mm, 25 * mm, 18 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 4 * mm))

    story.append(_p("Export files (SHA-256)", h2))
    for e in export_hashes:
        story.append(_p(f"{e.get('kind')}: {e.get('sha256')}", small))
    story.append(Spacer(1, 6 * mm))
    story.append(_p(DISCLAIMER, body))
    story.append(_p(CLOUD_FOOTNOTE if cloud_used else MOCK_FOOTNOTE, small))
    doc.build(story)
    return buf.getvalue()
