from __future__ import annotations

import html
import io
import re
from pathlib import Path
from typing import Any


_PDF_TEXT_TRANSLATION = str.maketrans(
    {
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2022": "-",
        "\u00a0": " ",
    }
)


def _missing_dependency_error(packages: str, use_case: str) -> RuntimeError:
    return RuntimeError(
        f"{use_case} requires {packages}. Install project dependencies again so PDF support is available."
    )


def strip_markdown_code_fence(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("```"):
        return text
    text = re.sub(r"^```[^\n]*\n", "", text, count=1)
    text = re.sub(r"\n```\s*$", "", text, count=1)
    return text.strip()


def _normalize_text(value: str) -> str:
    text = strip_markdown_code_fence(str(value or ""))
    text = text.translate(_PDF_TEXT_TRANSLATION).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_pdf_bytes(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise _missing_dependency_error("pypdf", "Resume PDF extraction") from exc

    reader = PdfReader(io.BytesIO(data))
    pages = [_normalize_text(page.extract_text() or "") for page in reader.pages]
    text = _normalize_text("\n\n".join(page for page in pages if page))
    if not text:
        raise RuntimeError("Could not extract text from uploaded resume PDF.")
    return text


def _pdf_dependencies() -> tuple[Any, ...]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise _missing_dependency_error("reportlab", "PDF generation") from exc

    return (
        colors,
        TA_LEFT,
        LETTER,
        ParagraphStyle,
        getSampleStyleSheet,
        inch,
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )


def _build_styles() -> dict[str, Any]:
    colors, text_align_left, _letter, paragraph_style, get_sample_style_sheet, _inch, *_unused = _pdf_dependencies()
    styles = get_sample_style_sheet()
    body = paragraph_style(
        "ResumeBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=13.5,
        alignment=text_align_left,
        spaceAfter=6,
    )
    return {
        "title": paragraph_style(
            "PdfTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=20,
            textColor=colors.HexColor("#10233d"),
            spaceAfter=8,
        ),
        "subtitle": paragraph_style(
            "PdfSubtitle",
            parent=body,
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#526173"),
            spaceAfter=10,
        ),
        "heading": paragraph_style(
            "PdfHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            textColor=colors.HexColor("#17324d"),
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": body,
        "compact": paragraph_style("PdfCompact", parent=body, fontSize=9.5, leading=12, spaceAfter=4),
        "table_header": paragraph_style(
            "PdfTableHeader",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.white,
        ),
    }


def _escape_paragraph_text(text: str) -> str:
    return html.escape(_normalize_text(text)).replace("\n", "<br/>")


def _line_is_heading(line: str) -> bool:
    if line.startswith("#"):
        return True
    if len(line) > 72:
        return False
    if line.endswith(":"):
        return True
    words = [word for word in re.split(r"\s+", line) if word]
    return bool(words) and line == line.upper() and len(words) <= 6


def write_text_pdf(text: str, output_path: Path, *, title: str, subtitle: str | None = None) -> Path:
    _colors, _text_align_left, letter, _paragraph_style, _sample, inch, list_flowable, list_item, paragraph, simple_doc_template, spacer, _table, _table_style, _page_break = _pdf_dependencies()
    styles = _build_styles()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    story: list[Any] = [paragraph(_escape_paragraph_text(title), styles["title"])]
    if subtitle:
        story.append(paragraph(_escape_paragraph_text(subtitle), styles["subtitle"]))

    lines = _normalize_text(text).split("\n")
    bullet_buffer: list[str] = []

    def flush_bullets() -> None:
        nonlocal bullet_buffer
        if not bullet_buffer:
            return
        items = [list_item(paragraph(_escape_paragraph_text(item), styles["compact"])) for item in bullet_buffer]
        story.append(list_flowable(items, bulletType="bullet", leftIndent=14, bulletFontName="Helvetica", bulletFontSize=8))
        story.append(spacer(1, 0.08 * inch))
        bullet_buffer = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_bullets()
            story.append(spacer(1, 0.08 * inch))
            continue
        normalized_heading = re.sub(r"^#+\s*", "", line).strip()
        bullet_match = re.match(r"^[-*]\s+(.*)$", line)
        if bullet_match:
            bullet_buffer.append(bullet_match.group(1))
            continue
        flush_bullets()
        if _line_is_heading(line):
            story.append(paragraph(_escape_paragraph_text(normalized_heading), styles["heading"]))
        else:
            story.append(paragraph(_escape_paragraph_text(line), styles["body"]))

    flush_bullets()
    doc = simple_doc_template(
        str(output_path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=title,
        author="Autopilot Jobhunt",
    )
    doc.build(story)
    return output_path


def write_jobs_pdf(jobs: list[dict[str, Any]], output_path: Path, *, title: str, subtitle: str, min_score: int) -> Path:
    colors, _text_align_left, letter, _paragraph_style, _sample, inch, _list_flowable, _list_item, paragraph, simple_doc_template, spacer, table, table_style, _page_break = _pdf_dependencies()
    styles = _build_styles()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = simple_doc_template(
        str(output_path),
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=title,
        author="Autopilot Jobhunt",
    )
    story: list[Any] = [
        paragraph(_escape_paragraph_text(title), styles["title"]),
        paragraph(_escape_paragraph_text(subtitle), styles["subtitle"]),
        spacer(1, 0.08 * inch),
    ]
    rows: list[list[Any]] = [[
        paragraph("Score", styles["table_header"]),
        paragraph("Company / Role", styles["table_header"]),
        paragraph("Location", styles["table_header"]),
        paragraph("Application URL", styles["table_header"]),
        paragraph("Why It Fits", styles["table_header"]),
    ]]
    for job in jobs:
        company = str(job.get("company") or "Unknown company").strip()
        role = str(job.get("extracted_title") or job.get("title") or "Unknown role").strip()
        rows.append(
            [
                paragraph(_escape_paragraph_text(str(job.get("score") or "")), styles["compact"]),
                paragraph(f"{html.escape(_normalize_text(company))}<br/>{html.escape(_normalize_text(role))}", styles["compact"]),
                paragraph(_escape_paragraph_text(str(job.get("location_remote") or job.get("location") or "-")), styles["compact"]),
                paragraph(_escape_paragraph_text(str(job.get("url") or "-")), styles["compact"]),
                paragraph(_escape_paragraph_text(str(job.get("reason") or "-")), styles["compact"]),
            ]
        )
    result_table = table(
        rows,
        colWidths=[0.55 * inch, 1.65 * inch, 1.05 * inch, 2.0 * inch, 2.0 * inch],
        repeatRows=1,
    )
    result_table.setStyle(
        table_style(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#c6d1dd")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dde5")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fb")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(result_table)
    story.append(spacer(1, 0.12 * inch))
    story.append(paragraph(_escape_paragraph_text(f"Included {len(jobs)} jobs with score >= {min_score}."), styles["subtitle"]))
    doc.build(story)
    return output_path
