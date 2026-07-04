from __future__ import annotations

import csv
import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .pdf import write_jobs_pdf


EXPORT_FIELDS = [
    "Company",
    "Role",
    "Location",
    "Application URL",
    "Score (%)",
    "Stack",
    "Region",
    "Reason",
    "Worth Applying",
    "Scan Date",
]

_CSV_SAFE_TRANSLATION = str.maketrans(
    {
        "\u2192": "->",
        "\u2190": "<-",
        "\u2014": "-",
        "\u2013": "-",
        "\u2022": "-",
        "\u2026": "...",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
)


def sanitize_csv_text(value: object) -> str:
    text = str(value or "")
    text = text.translate(_CSV_SAFE_TRANSLATION)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def job_to_row(job: dict[str, Any]) -> dict[str, Any]:
    worth = job.get("worth_applying")
    return {
        "Company": sanitize_csv_text(job.get("company", "")),
        "Role": sanitize_csv_text(job.get("extracted_title") or job.get("title", "")),
        "Location": sanitize_csv_text(job.get("location_remote") or job.get("location", "")),
        "Application URL": sanitize_csv_text(job.get("url", "")),
        "Score (%)": job.get("score", ""),
        "Stack": sanitize_csv_text(job.get("stack", "")),
        "Region": sanitize_csv_text(job.get("region", "")),
        "Reason": sanitize_csv_text(job.get("reason", "")),
        "Worth Applying": "Yes" if worth else ("No" if worth is False else ""),
        "Scan Date": sanitize_csv_text(job.get("scan_date", "")),
    }


def write_jobs_csv(jobs: list[dict[str, Any]], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for job in jobs:
            writer.writerow(job_to_row(job))
    return output_path


def export_jobs(
    *,
    jobs: list[dict[str, Any]] | None = None,
    history_jobs: list[dict[str, Any]] | None = None,
    min_score: int = 0,
    days: int = 0,
    export_format: str = "csv",
    output_dir: Path,
) -> dict[str, str | None]:
    normalized_format = str(export_format or "csv").strip().lower()
    if normalized_format not in {"csv", "pdf", "both"}:
        raise SystemExit("export_format must be one of: csv, pdf, both")

    if days > 0:
        all_jobs = history_jobs or []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        source_jobs = [job for job in all_jobs if job.get("scan_date", "9999") >= cutoff]
        source_label = f"last {days} days"
    else:
        source_jobs = jobs or []
        source_label = "last scan"

    filtered = [job for job in source_jobs if job.get("score", 0) >= min_score]
    if not filtered:
        return {"csv_path": None, "pdf_path": None}

    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_last{days}d" if days else ""
    csv_path: Path | None = None
    pdf_path: Path | None = None

    if normalized_format in {"csv", "both"}:
        csv_path = write_jobs_csv(filtered, output_dir / f"jobs_{date_str}{suffix}.csv")

    if normalized_format in {"pdf", "both"}:
        pdf_path = output_dir / f"jobs_{date_str}{suffix}.pdf"
        write_jobs_pdf(
            filtered,
            pdf_path,
            title="Autopilot Jobhunt Results",
            subtitle=f"Source: {source_label} | Generated on {date_str}",
            min_score=min_score,
        )

    return {
        "csv_path": str(csv_path) if csv_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
    }
