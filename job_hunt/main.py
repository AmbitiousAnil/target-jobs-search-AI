#!/usr/bin/env python3
"""
Usage:
  autopilot init              - set up working directory (first-time pip install setup)
  autopilot scan              - run daily job scan
  autopilot draft #1          - draft application for job #1 from last scan
  autopilot draft https://... - draft application for a specific URL
  autopilot export            - export last scan to CSV (output/jobs_YYYY-MM-DD.csv)
  autopilot export --min 60   - export only jobs with score >= 60
  autopilot export --days 7   - export jobs from last 7 days (requires scan history)
  autopilot export --days 7 --min 60  - combine filters
  autopilot export --format pdf       - export to PDF instead of CSV
"""
import csv
import json
import os
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from autopilot_jobhunt.services.pdf_utils import write_jobs_pdf

from .config_utils import sanitize_nested_strings, stripped_env

_PLACEHOLDERS = {
    "YOUR_TINYFISH_API_KEY", "your_tinyfish_api_key_here",
    "YOUR_OPENROUTER_API_KEY", "your_openrouter_api_key_here",
    "YOUR_NVIDIA_API_KEY", "your_nvidia_api_key_here",
    "YOUR_ANTHROPIC_API_KEY", "your_anthropic_api_key_here",
}


def _is_placeholder(val: str) -> bool:
    return val in _PLACEHOLDERS or val.startswith("YOUR_") or val.endswith("_HERE") or val.endswith("_here")


def _use_env(val: str | None) -> bool:
    """An env var overrides config.json only if it's set and not a placeholder.

    Without the placeholder guard, the default `.env` template (which `autopilot
    init` writes with `your_..._here` values) would clobber real keys in
    config.json - the classic "config.json and .env don't compose" bug.
    """
    return bool(val) and not _is_placeholder(val)


def load_config() -> dict:
    load_dotenv(dotenv_path=Path(".env"), override=True)
    p = Path("config.json")
    if not p.exists():
        sys.exit("config.json not found.\nRun 'autopilot init' to set up your working directory.")

    config = sanitize_nested_strings(json.loads(p.read_text()))

    env_mapping = {
        "TINYFISH_API_KEY": "tinyfish_api_key",
        "LLM_PROVIDER": "llm_provider",
        "OPENROUTER_API_KEY": "openrouter_api_key",
        "OPENROUTER_MODEL": "openrouter_model",
        "OPENROUTER_FALLBACK_MODELS": "openrouter_fallback_models",
        "NVIDIA_API_KEY": "nvidia_api_key",
        "NVIDIA_MODEL": "nvidia_model",
        "NVIDIA_FALLBACK_MODELS": "nvidia_fallback_models",
        "GOOGLE_API_KEY": "google_api_key",
        "GOOGLE_MODEL": "google_model",
        "GOOGLE_FALLBACK_MODELS": "google_fallback_models",
        "Z_AI_API_KEY": "z_ai_api_key",
        "Z_AI_MODEL": "z_ai_model",
        "Z_AI_FALLBACK_MODELS": "z_ai_fallback_models",
        "OLLAMA_API_KEY": "ollama_api_key",
        "OLLAMA_BASE_URL": "ollama_base_url",
        "OLLAMA_MODEL": "ollama_model",
        "OLLAMA_MAX_TOKENS": "ollama_max_tokens",
        "OLLAMA_FALLBACK_MODELS": "ollama_fallback_models",
        "CLAUDE_CLI_MODEL": "claude_cli_model",
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "ANTHROPIC_MODEL": "anthropic_model",
    }

    for env_key, config_key in env_mapping.items():
        val = stripped_env(env_key)
        if _use_env(val):
            if env_key in (
                "OPENROUTER_FALLBACK_MODELS",
                "NVIDIA_FALLBACK_MODELS",
                "GOOGLE_FALLBACK_MODELS",
                "Z_AI_FALLBACK_MODELS",
                "OLLAMA_FALLBACK_MODELS",
            ):
                config[config_key] = [m.strip() for m in val.split(",")]
            else:
                config[config_key] = val

    tinyfish_key = str(config.get("tinyfish_api_key", "") or "").strip()
    if not tinyfish_key or _is_placeholder(tinyfish_key):
        sys.exit(
            "TINYFISH_API_KEY not set.\n"
            "Add it to your .env file: TINYFISH_API_KEY=sk-tinyfish-...\n"
            "Get a key at https://agent.tinyfish.ai"
        )

    cand_name = stripped_env("CANDIDATE_NAME")
    cand_resume = stripped_env("RESUME_PATH")
    cand_min_score = stripped_env("MIN_SCORE")
    cand_top_n = stripped_env("TOP_N")
    if cand_name or cand_resume or cand_min_score or cand_top_n:
        if "candidate" not in config:
            config["candidate"] = {}
        if cand_name:
            config["candidate"]["name"] = cand_name
        if cand_resume:
            config["candidate"]["resume_path"] = cand_resume
        if cand_min_score:
            config["candidate"]["min_score"] = int(cand_min_score)
        if cand_top_n:
            config["candidate"]["top_n"] = int(cand_top_n)

    return config


def load_companies() -> list:
    p = Path("companies.json")
    if not p.exists():
        sys.exit("companies.json not found.\nRun 'autopilot init' to set up your working directory.")
    return json.loads(p.read_text())


def init_project() -> None:
    import importlib.resources as pkg_resources

    cwd = Path.cwd()
    data_pkg = pkg_resources.files("job_hunt.data")

    def _copy(src_name: str, dest: Path, label: str) -> None:
        if dest.exists():
            print(f"  {dest.name} already exists, skipping")
        else:
            dest.write_text(data_pkg.joinpath(src_name).read_text(encoding="utf-8"), encoding="utf-8")
            print(f"✓ {label}")

    _copy("companies.json", cwd / "companies.json", "companies.json created (130+ companies pre-loaded)")
    _copy("config.example.json", cwd / "config.json", "config.json created - fill in your API keys and profile")
    _copy("env_example", cwd / ".env", ".env created - fill in your API keys")

    resume_dir = cwd / "resume"
    resume_dir.mkdir(exist_ok=True)
    _copy("resume_template.md", resume_dir / "YOUR_RESUME.md", "resume/YOUR_RESUME.md created - replace with your resume")

    (cwd / "state").mkdir(exist_ok=True)
    (cwd / "output").mkdir(exist_ok=True)

    print("\nNext:")
    print("  1. Edit config.json - set your name, profile, and API keys")
    print("  2. Replace resume/YOUR_RESUME.md with your actual resume")
    print("  3. Run: autopilot scan")


LAST_SCAN_FILE = Path("state/last_scan.json")
JOB_HISTORY_FILE = Path("state/job_history.json")

EXPORT_FIELDS = [
    "Company", "Role", "Location", "Application URL",
    "Score (%)", "Stack", "Region", "Reason", "Worth Applying", "Scan Date",
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


def _sanitize_csv_text(value: object) -> str:
    text = str(value or "")
    text = text.translate(_CSV_SAFE_TRANSLATION)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def _job_to_row(j: dict) -> dict:
    worth = j.get("worth_applying")
    return {
        "Company": _sanitize_csv_text(j.get("company", "")),
        "Role": _sanitize_csv_text(j.get("extracted_title") or j.get("title", "")),
        "Location": _sanitize_csv_text(j.get("location_remote") or j.get("location", "")),
        "Application URL": _sanitize_csv_text(j.get("url", "")),
        "Score (%)": j.get("score", ""),
        "Stack": _sanitize_csv_text(j.get("stack", "")),
        "Region": _sanitize_csv_text(j.get("region", "")),
        "Reason": _sanitize_csv_text(j.get("reason", "")),
        "Worth Applying": "Yes" if worth else ("No" if worth is False else ""),
        "Scan Date": _sanitize_csv_text(j.get("scan_date", "")),
    }


def _parse_export_args(argv: list[str]) -> tuple[int, int, str]:
    """Parse --min / --days / --format flags for the export command. No API keys required."""
    min_score = 0
    days = 0
    export_format = "csv"
    if "--min" in argv:
        idx = argv.index("--min")
        try:
            min_score = int(argv[idx + 1])
        except (IndexError, ValueError):
            sys.exit("--min requires an integer, e.g. --min 60")
    if "--days" in argv:
        idx = argv.index("--days")
        try:
            days = int(argv[idx + 1])
        except (IndexError, ValueError):
            sys.exit("--days requires an integer, e.g. --days 7")
    if "--format" in argv:
        idx = argv.index("--format")
        try:
            export_format = str(argv[idx + 1]).strip().lower()
        except IndexError:
            sys.exit("--format requires one of: csv, pdf, both")
    return min_score, days, export_format


def export_jobs(
    min_score: int = 0,
    days: int = 0,
    export_format: str = "csv",
) -> dict[str, str | None]:
    normalized_format = str(export_format or "csv").strip().lower()
    if normalized_format not in {"csv", "pdf", "both"}:
        sys.exit("export_format must be one of: csv, pdf, both")

    if days > 0:
        if not JOB_HISTORY_FILE.exists():
            sys.exit(
                "No history yet. Run 'autopilot scan' at least once after this update."
            )
        all_jobs: list[dict] = json.loads(JOB_HISTORY_FILE.read_text())
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        jobs = [j for j in all_jobs if j.get("scan_date", "9999") >= cutoff]
        source_label = f"last {days} days"
    else:
        if not LAST_SCAN_FILE.exists():
            sys.exit("No scan found. Run: autopilot scan")
        jobs = json.loads(LAST_SCAN_FILE.read_text())
        source_label = "last scan"

    filtered = [j for j in jobs if j.get("score", 0) >= min_score]

    if not filtered:
        print(f"No jobs with score >= {min_score} in {source_label}")
        return {"csv_path": None, "pdf_path": None}

    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_last{days}d" if days else ""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    csv_path: Path | None = None
    pdf_path: Path | None = None

    if normalized_format in {"csv", "both"}:
        csv_path = output_dir / f"jobs_{date_str}{suffix}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
            writer.writeheader()
            for j in filtered:
                writer.writerow(_job_to_row(j))
        print(f"Exported {len(filtered)} jobs ({source_label}) -> {csv_path}")

    if normalized_format in {"pdf", "both"}:
        pdf_path = output_dir / f"jobs_{date_str}{suffix}.pdf"
        write_jobs_pdf(
            filtered,
            pdf_path,
            title="Autopilot Jobhunt Results",
            subtitle=f"Source: {source_label} | Generated on {date_str}",
            min_score=min_score,
        )
        print(f"Exported {len(filtered)} jobs ({source_label}) -> {pdf_path}")

    if min_score:
        print(f"Filter: score >= {min_score} (skipped {len(jobs) - len(filtered)})")

    return {
        "csv_path": str(csv_path) if csv_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
    }


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "init":
        init_project()
        return

    # export reads local scan state only - no API keys needed, so skip load_config()
    if cmd == "export":
        min_score, days, export_format = _parse_export_args(sys.argv)
        export_jobs(min_score=min_score, days=days, export_format=export_format)
        return

    config = load_config()

    if cmd == "scan":
        from job_hunt.scanner import run_scan
        run_scan(config, load_companies())

    elif cmd == "draft":
        if len(sys.argv) < 3:
            sys.exit("Usage: autopilot draft #N  or  autopilot draft URL")
        from job_hunt.drafter import draft_application
        draft_application(config, sys.argv[2])

    else:
        sys.exit(f"Unknown command: {cmd}\nUse: scan | draft | export")


if __name__ == "__main__":
    main()
