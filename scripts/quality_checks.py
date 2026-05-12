"""Data Quality Framework.

Implements seven independent checks (the brief asks for at least five). Each
check returns a structured result so the dispatcher can decide severity and
alert routing without re-running the check. Results are persisted to
`outputs/dq_results.json` and a human-readable extract is appended to
`outputs/data_quality_report.md`.

Checks implemented:

  1. FRESHNESS - latest snapshot is within `max_days_between_snapshots`
  2. UNIQUENESS - no (loan_id, snapshot_date) duplicates in credit
  3. REFERENTIAL_INTEGRITY - >=95% of credit loan_ids appear in customer master
  4. RANGE_CUSTOMER_AGE - customer age between [18, 100] when present
  5. RANGE_DAYS_PAST_DUE - days_past_due between [0, 3650]
  6. NULL_THRESHOLDS - critical join keys below configured null percentages
  7. SCHEMA_DRIFT - mandatory canonical columns present in every snapshot

Each result has shape:
  {
    "name": ...,                # check id
    "severity": "LOW|MEDIUM|HIGH|CRITICAL",
    "status": "PASS|FAIL|WARN",
    "expected": ...,
    "observed": ...,
    "message": "human readable",
    "evidence_path": optional file containing failing rows for triage
  }

Alerting is routed via `utils.dispatch_alert` so failing checks log to the
JSONL stream where SREs can pipe to their preferred destination.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from utils import (
    ANNEX_ROOT,
    dispatch_alert,
    ensure_dirs,
    get_logger,
    load_config,
    log_event,
    resolve_paths,
    timed,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
# Standard return shape for every data-quality check.
@dataclass
class CheckResult:
    name: str
    severity: str
    status: str
    expected: Any
    observed: Any
    message: str
    evidence_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # True only when the check passed cleanly.
    @property
    def passed(self) -> bool:
        return self.status == "PASS"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
# Verify the latest credit snapshot is recent enough.
def check_freshness(credit: pd.DataFrame, cfg: dict[str, Any]) -> CheckResult:
    snaps = sorted(pd.to_datetime(credit["snapshot_date"].unique()))
    if not snaps:
        return CheckResult("FRESHNESS", "CRITICAL", "FAIL",
                           "at least 1 snapshot", "0",
                           "No snapshots present")
    latest = snaps[-1]
    cadence = cfg["quality"]["freshness"]["max_days_between_snapshots"]
    # Treat "today" as the case-study reference date (latest snapshot in the file
    # set); in production this would be `datetime.utcnow()`.
    age = (max(latest, pd.Timestamp.utcnow().tz_localize(None)) - latest).days
    status = "PASS" if age <= cadence else "FAIL"
    return CheckResult(
        "FRESHNESS", "HIGH", status,
        expected=f"latest snapshot <= {cadence} days old",
        observed=f"latest={latest.date()}, age_days={age}",
        message=f"Latest snapshot is {latest.date()} ({age} days old).",
    )


# Check that (loan_id, snapshot_date) is unique across credit rows.
def check_uniqueness(credit: pd.DataFrame, paths) -> CheckResult:
    key = ["loan_id", "snapshot_date"]
    dup_mask = credit.duplicated(subset=key, keep=False)
    n_dups = int(dup_mask.sum())
    status = "PASS" if n_dups == 0 else "FAIL"
    evidence = None
    # Persist offending rows to a CSV for triage.
    if n_dups:
        evidence = paths.outputs / "dq_duplicates.csv"
        credit.loc[dup_mask].to_csv(evidence, index=False)
    return CheckResult(
        "UNIQUENESS", "CRITICAL", status,
        expected="0 duplicate (loan_id, snapshot_date) rows",
        observed=f"{n_dups} duplicate rows",
        message=f"Found {n_dups} duplicate rows on primary key.",
        evidence_path=str(evidence) if evidence else None,
    )


# Check that credit loan_ids mostly exist in the customer master.
def check_referential_integrity(credit: pd.DataFrame, customers: pd.DataFrame,
                                cfg: dict[str, Any], paths) -> CheckResult:
    cust_ids = set(customers["loan_id"].dropna().unique())
    credit_ids = credit["loan_id"].dropna()
    if credit_ids.empty:
        return CheckResult("REFERENTIAL_INTEGRITY", "HIGH", "FAIL",
                           "credit not empty", "empty", "No credit rows")
    coverage = credit_ids.isin(cust_ids).mean()
    threshold = cfg["quality"]["referential_integrity"]["credit_to_sales_min_coverage"]
    status = "PASS" if coverage >= threshold else "FAIL"
    missing = sorted(set(credit_ids) - cust_ids)[:25]
    return CheckResult(
        "REFERENTIAL_INTEGRITY", "HIGH", status,
        expected=f"coverage >= {threshold:.0%}",
        observed=f"coverage={coverage:.3%}",
        message=(f"{coverage:.2%} of credit loan_ids match a customer record."),
        extra={"sample_unmatched": missing},
    )


# Check that customer ages sit in the configured [min, max] window.
def check_range_customer_age(features: pd.DataFrame, cfg: dict[str, Any]) -> CheckResult:
    lo = cfg["quality"]["ranges"]["age_min"]
    hi = cfg["quality"]["ranges"]["age_max"]
    s = pd.to_numeric(features.get("customer_age_years"), errors="coerce").dropna()
    if s.empty:
        return CheckResult("RANGE_CUSTOMER_AGE", "MEDIUM", "WARN",
                           f"age in [{lo},{hi}]", "no data",
                           "No customer_age_years observations available")
    bad = ((s < lo) | (s > hi)).sum()
    status = "PASS" if bad == 0 else "FAIL"
    return CheckResult(
        "RANGE_CUSTOMER_AGE", "MEDIUM", status,
        expected=f"age in [{lo}, {hi}]",
        observed=f"{int(bad)} out-of-range / {len(s)} non-null",
        message=f"{int(bad)} ages outside [{lo},{hi}]. min={s.min():.1f}, max={s.max():.1f}",
    )


# Check that days_past_due sits in the configured range.
def check_range_dpd(features: pd.DataFrame, cfg: dict[str, Any]) -> CheckResult:
    lo = cfg["quality"]["ranges"]["days_past_due_min"]
    hi = cfg["quality"]["ranges"]["days_past_due_max"]
    s = pd.to_numeric(features["days_past_due"], errors="coerce")
    bad = ((s < lo) | (s > hi)).sum()
    status = "PASS" if bad == 0 else "FAIL"
    return CheckResult(
        "RANGE_DAYS_PAST_DUE", "HIGH", status,
        expected=f"days_past_due in [{lo}, {hi}]",
        observed=f"{int(bad)} out-of-range / {len(s)}",
        message=f"{int(bad)} DPD values outside [{lo},{hi}].",
    )


# Check that null rates of critical columns are below configured thresholds.
def check_null_thresholds(credit: pd.DataFrame, cfg: dict[str, Any]) -> list[CheckResult]:
    thresholds = cfg["quality"]["nulls"]["customer_id_columns"]
    results: list[CheckResult] = []
    # One result per configured column.
    for col, max_pct in thresholds.items():
        col_l = col.lower()
        # Required column is missing entirely.
        if col_l not in credit.columns:
            results.append(CheckResult(
                f"NULL_{col}", "HIGH", "FAIL",
                f"<= {max_pct:.1%} null", "column absent",
                f"Required column `{col}` missing from credit"))
            continue
        # Compare observed null rate to threshold.
        pct = credit[col_l].isna().mean()
        status = "PASS" if pct <= max_pct else "FAIL"
        results.append(CheckResult(
            f"NULL_{col}", "MEDIUM" if max_pct > 0 else "HIGH", status,
            expected=f"<= {max_pct:.1%} null",
            observed=f"{pct:.3%} null",
            message=f"`{col}` is {pct:.2%} null."
        ))
    return results


# Check that the canonical credit schema is present in the staged data.
def check_schema_drift(credit: pd.DataFrame, cfg: dict[str, Any]) -> CheckResult:
    expected = [c.lower() for c in cfg["quality"]["schema_drift"]["credit_expected_columns"]]
    missing = [c for c in expected if c not in credit.columns]
    status = "PASS" if not missing else "FAIL"
    return CheckResult(
        "SCHEMA_DRIFT", "CRITICAL", status,
        expected=f"columns present: {expected}",
        observed=f"missing: {missing}" if missing else "all present",
        message=("Schema drift detected: " + ", ".join(missing)) if missing else
                "Canonical schema honoured by all snapshots.",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
# Run every data-quality check and dispatch alerts for failures.
def run_all(paths, cfg, logger) -> list[CheckResult]:
    # Load the inputs each check needs.
    credit = pd.read_parquet(paths.staging / "credit_snapshots.parquet")
    customers = pd.read_parquet(paths.staging / "customers.parquet")
    features = pd.read_parquet(paths.curated / "portfolio_features.parquet")

    # Execute checks in order.
    results: list[CheckResult] = []
    results.append(check_freshness(credit, cfg))
    results.append(check_uniqueness(credit, paths))
    results.append(check_referential_integrity(credit, customers, cfg, paths))
    results.append(check_range_customer_age(features, cfg))
    results.append(check_range_dpd(features, cfg))
    results.extend(check_null_thresholds(credit, cfg))
    results.append(check_schema_drift(credit, cfg))

    # Send alerts for any failed or warning checks.
    for r in results:
        if r.status in ("FAIL", "WARN"):
            dispatch_alert(
                logger, cfg,
                severity=r.severity,
                title=f"DQ {r.status}: {r.name}",
                body=r.message,
                context={"expected": r.expected, "observed": r.observed,
                         "evidence_path": r.evidence_path},
            )
    return results


# Render the check results as a Markdown report.
def render_report(results: list[CheckResult]) -> str:
    # Header + summary table.
    parts = ["## Data Quality Check Results",
             "",
             f"_Generated: {datetime.utcnow().isoformat()}Z_",
             "",
             "| Check | Severity | Status | Expected | Observed |",
             "|-------|----------|--------|----------|----------|"]
    for r in results:
        parts.append(f"| {r.name} | {r.severity} | **{r.status}** | {r.expected} | {r.observed} |")
    parts.append("")
    parts.append("### Failure detail")
    parts.append("")
    # Detail section for any failed checks.
    failed = [r for r in results if not r.passed]
    if not failed:
        parts.append("_All checks passed._")
    else:
        for r in failed:
            parts.append(f"- **{r.name}**: {r.message}")
            if r.evidence_path:
                parts.append(f"  - Evidence: `{r.evidence_path}`")
    return "\n".join(parts)


# CLI entrypoint: run all DQ checks and write report + JSON outputs.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args.
    parser = argparse.ArgumentParser(description="Run data quality checks")
    parser.add_argument("--config", default=None)
    parser.add_argument("--fail-on-fail", action="store_true",
                        help="Exit non-zero if any check FAILed")
    args = parser.parse_args(argv)

    # Load config + set up directories and logger.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("dq", paths.logs)

    # Run every quality check.
    with timed(logger, "dq_checks"):
        results = run_all(paths, cfg, logger)

    # Write machine-readable JSON results.
    (paths.outputs / "dq_results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, default=str),
        encoding="utf-8",
    )

    # Append the human-readable section to the data quality report.
    md = render_report(results)
    report = paths.outputs / "data_quality_report.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    report.write_text(existing + "\n\n" + md, encoding="utf-8")

    summary = {r.name: r.status for r in results}
    log_event(logger, "dq_complete", summary=summary)
    print("OK  data quality:", summary)

    if args.fail_on_fail and any(r.status == "FAIL" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
