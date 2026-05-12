"""Data profiling for the three source domains.

Outputs:
  - outputs/profile_<dataset>.json  - machine readable per-column profile
  - outputs/data_quality_report.md  - human readable summary with findings
  - logs/pipeline-*.jsonl           - structured event log

Run standalone:
  python scripts/data_profiling.py

The script is idempotent and reads only the raw files; it never mutates them.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from utils import (
    ANNEX_ROOT,
    ensure_dirs,
    get_logger,
    list_credit_files,
    load_config,
    log_event,
    parse_snapshot_date,
    resolve_paths,
    timed,
)


# ---------------------------------------------------------------------------
# Per-column profiler
# ---------------------------------------------------------------------------
# Build a profile dict (nulls, distincts, stats) for every column in a DataFrame.
def profile_dataframe(df: pd.DataFrame, *, dataset: str, source: str) -> dict[str, Any]:
    n = len(df)
    columns: list[dict[str, Any]] = []
    # Compute per-column metrics.
    for col in df.columns:
        s = df[col]
        nulls = int(s.isna().sum())
        unique = int(s.nunique(dropna=True))
        col_profile: dict[str, Any] = {
            "name": col,
            "dtype": str(s.dtype),
            "null_count": nulls,
            "null_pct": round(nulls / n * 100, 3) if n else 0.0,
            "distinct": unique,
            "distinct_pct": round(unique / n * 100, 3) if n else 0.0,
        }
        # Numeric columns: add summary statistics.
        if pd.api.types.is_numeric_dtype(s):
            non_null = s.dropna()
            if not non_null.empty:
                col_profile.update(
                    min=float(non_null.min()),
                    max=float(non_null.max()),
                    mean=round(float(non_null.mean()), 3),
                    median=float(non_null.median()),
                    std=round(float(non_null.std() or 0), 3),
                )
        else:
            # Non-numeric columns: show top 5 most-common values.
            top = s.dropna().astype(str).value_counts().head(5)
            col_profile["top_values"] = {str(k): int(v) for k, v in top.items()}
        columns.append(col_profile)

    # Return the full per-dataset profile.
    return {
        "dataset": dataset,
        "source": str(source),
        "row_count": int(n),
        "column_count": int(df.shape[1]),
        "profiled_at": datetime.utcnow().isoformat() + "Z",
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# Loaders that return labelled frames so we can profile each in isolation
# ---------------------------------------------------------------------------
# Load each credit CSV snapshot, keyed by its parsed snapshot date.
def load_credit_snapshots(paths, cfg, logger) -> dict[str, pd.DataFrame]:
    files = list_credit_files(paths)
    if not files:
        raise FileNotFoundError(f"No credit files matched in {paths.raw_credit_dir}")
    pattern = cfg["ingest"]["filename_date_pattern"]
    fmt = cfg["ingest"]["filename_date_format"]
    out: dict[str, pd.DataFrame] = {}
    # Read each file and tag it with the date extracted from its filename.
    for f in files:
        snap = parse_snapshot_date(f.name, pattern, fmt).date().isoformat()
        df = pd.read_csv(f, **cfg["ingest"]["csv_read"])
        out[f"credit_{snap}"] = df
        log_event(logger, "load_credit", file=f.name, snapshot=snap, rows=len(df))
    return out


# Load every sheet from the sales Excel workbook into its own DataFrame.
def load_sales_sheets(paths, logger) -> dict[str, pd.DataFrame]:
    xl = pd.ExcelFile(paths.raw_sales_xlsx)
    sheets: dict[str, pd.DataFrame] = {}
    for s in xl.sheet_names:
        df = pd.read_excel(paths.raw_sales_xlsx, sheet_name=s)
        sheets[f"sales_{s.lower().replace(' ', '_')}"] = df
        log_event(logger, "load_sales_sheet", sheet=s, rows=len(df))
    return sheets


# Load the NPS Excel file as a single DataFrame.
def load_nps(paths, logger) -> dict[str, pd.DataFrame]:
    df = pd.read_excel(paths.raw_nps_xlsx)
    log_event(logger, "load_nps", rows=len(df))
    return {"nps": df}


# ---------------------------------------------------------------------------
# Findings - heuristics that flag the most common real-world issues
# ---------------------------------------------------------------------------
# Scan profiles to flag obvious data-quality issues for the report.
def derive_findings(profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    # 1. Flag loan_id columns with high NULL rates (poor join coverage).
    for name, prof in profiles.items():
        for col in prof["columns"]:
            if col["name"].lower() in {"loan id", "loan_id"} and col["null_pct"] > 5:
                findings.append({
                    "severity": "HIGH",
                    "dataset": name,
                    "issue": "join_key_null",
                    "detail": f"{col['name']} is {col['null_pct']}% NULL - join coverage will be poor",
                })

    # 2. Flag date-named columns that came in as plain text.
    for name, prof in profiles.items():
        for col in prof["columns"]:
            if col["dtype"] == "object" and any(tok in col["name"].lower() for tok in ("date", "expiry")):
                findings.append({
                    "severity": "MEDIUM",
                    "dataset": name,
                    "issue": "date_as_string",
                    "detail": f"{col['name']} is stored as text - needs parse-and-cast",
                })

    # 3. Flag ID-like columns where duplicates likely exist.
    for name, prof in profiles.items():
        for col in prof["columns"]:
            if col["name"].lower().endswith("_id") and prof["row_count"] > 100:
                if col.get("distinct_pct", 0) < 95 and col["null_pct"] < 5:
                    findings.append({
                        "severity": "MEDIUM",
                        "dataset": name,
                        "issue": "duplicate_ids",
                        "detail": f"{col['name']} is only {col['distinct_pct']}% distinct - possible duplicates",
                    })

    # 4. Flag NPS column headers that contain unicode replacement chars (mojibake).
    for name, prof in profiles.items():
        if "nps" in name:
            for col in prof["columns"]:
                if "�" in col["name"] or "?" in col["name"][:1]:
                    findings.append({
                        "severity": "LOW",
                        "dataset": name,
                        "issue": "encoding_artifact",
                        "detail": f"Column header contains unicode replacement char: {col['name']!r}",
                    })

    return findings


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
# Render profiles + findings into a human-readable Markdown report.
def render_markdown_report(profiles: dict[str, dict[str, Any]],
                           findings: list[dict[str, Any]]) -> str:
    # Header section.
    parts = ["# Data Quality Report",
             "",
             f"_Generated: {datetime.utcnow().isoformat()}Z_",
             "",
             "## Summary",
             ""]
    # One bullet per dataset with row/column counts.
    for name, prof in profiles.items():
        parts.append(f"- **{name}** - {prof['row_count']:,} rows x {prof['column_count']} columns - source: `{Path(prof['source']).name}`")
    parts.append("")
    parts.append("## Findings")
    parts.append("")
    # Findings table (or empty message).
    if not findings:
        parts.append("_No issues detected by heuristics._")
    else:
        parts.append("| Severity | Dataset | Issue | Detail |")
        parts.append("|----------|---------|-------|--------|")
        for f in findings:
            parts.append(f"| {f['severity']} | `{f['dataset']}` | {f['issue']} | {f['detail']} |")
    parts.append("")
    parts.append("## Per-column null percentage (>= 1%)")
    parts.append("")
    # Per-dataset table of columns with notable null rates.
    for name, prof in profiles.items():
        rows = [c for c in prof["columns"] if c["null_pct"] >= 1.0]
        if not rows:
            continue
        parts.append(f"### `{name}`")
        parts.append("")
        parts.append("| Column | Dtype | Nulls % | Distinct |")
        parts.append("|--------|-------|---------|----------|")
        for c in sorted(rows, key=lambda r: r["null_pct"], reverse=True):
            parts.append(f"| `{c['name']}` | {c['dtype']} | {c['null_pct']}% | {c['distinct']} |")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
# CLI entrypoint: profile all sources and write JSON + Markdown outputs.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args.
    parser = argparse.ArgumentParser(description="Profile raw source datasets")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    # Load config and prepare output directories + logger.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("profile", paths.logs)

    profiles: dict[str, dict[str, Any]] = {}

    # Profile each credit snapshot CSV.
    with timed(logger, "profile_credit"):
        for name, df in load_credit_snapshots(paths, cfg, logger).items():
            src = paths.raw_credit_dir / f"{name.replace('credit_', 'Credit Data - ')}.csv"
            profiles[name] = profile_dataframe(df, dataset=name, source=src)

    # Profile each sales Excel sheet.
    with timed(logger, "profile_sales"):
        for name, df in load_sales_sheets(paths, logger).items():
            profiles[name] = profile_dataframe(df, dataset=name, source=paths.raw_sales_xlsx)

    # Profile the NPS dataset.
    with timed(logger, "profile_nps"):
        for name, df in load_nps(paths, logger).items():
            profiles[name] = profile_dataframe(df, dataset=name, source=paths.raw_nps_xlsx)

    # Run heuristic checks across all profiles.
    findings = derive_findings(profiles)

    # Write one JSON profile file per dataset.
    for name, prof in profiles.items():
        (paths.outputs / f"profile_{name}.json").write_text(
            json.dumps(prof, indent=2), encoding="utf-8"
        )

    # Write the consolidated Markdown report.
    report_md = render_markdown_report(profiles, findings)
    (paths.outputs / "data_quality_report.md").write_text(report_md, encoding="utf-8")

    log_event(logger, "profile_complete", datasets=len(profiles), findings=len(findings))
    print(f"OK  profiled {len(profiles)} datasets - findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
