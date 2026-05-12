"""Shared utilities: config loading, structured logging, IO helpers, alerting hook.

The aim is to keep every other script tiny and readable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


# Project root paths used across all scripts.
ANNEX_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ANNEX_ROOT.parent
DEFAULT_CONFIG = ANNEX_ROOT / "config" / "pipeline.yaml"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Holds all input/output paths used by the pipeline.
@dataclass(frozen=True)
class Paths:
    raw_credit_dir: Path
    raw_credit_glob: str
    raw_sales_xlsx: Path
    raw_nps_xlsx: Path
    raw_defs_xlsx: Path
    staging: Path
    curated: Path
    warehouse: Path
    outputs: Path
    logs: Path


# Load the YAML config file into a dict.
def load_config(path: Path | str | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Build a Paths object from the config dict.
def resolve_paths(cfg: dict[str, Any]) -> Paths:
    p = cfg["paths"]

    # Make a config-relative path absolute under the project root.
    def under_annex(rel: str) -> Path:
        return (ANNEX_ROOT / rel).resolve()

    return Paths(
        raw_credit_dir=under_annex(p["raw"]["credit_dir"]),
        raw_credit_glob=p["raw"]["credit_glob"],
        raw_sales_xlsx=under_annex(p["raw"]["sales_xlsx"]),
        raw_nps_xlsx=under_annex(p["raw"]["nps_xlsx"]),
        raw_defs_xlsx=under_annex(p["raw"]["definitions_xlsx"]),
        staging=under_annex(p["staging"]),
        curated=under_annex(p["curated"]),
        warehouse=under_annex(p["warehouse"]),
        outputs=under_annex(p["outputs"]),
        logs=under_annex(p["logs"]),
    )


# Create all output directories if they don't already exist.
def ensure_dirs(paths: Paths) -> None:
    for p in (paths.staging, paths.curated, paths.warehouse.parent, paths.outputs, paths.logs):
        p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Formatter that writes one JSON object per log record (machine-readable).
class _JsonFormatter(logging.Formatter):
    # Convert a log record into a JSON string.
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach exception info if present.
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra structured fields.
        extras = getattr(record, "extra_fields", None)
        if extras:
            payload.update(extras)
        return json.dumps(payload, default=str)


# Build a logger that writes to stdout, plus an optional JSONL file.
def get_logger(name: str, logs_dir: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    # Reuse the existing logger if already configured.
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    # Console handler with a human-readable format.
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s | %(message)s"))
    logger.addHandler(sh)

    # File handler that writes JSONL log lines (one per run).
    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        run_id = os.environ.get("PIPELINE_RUN_ID") or datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        fh = logging.FileHandler(logs_dir / f"pipeline-{run_id}.jsonl", encoding="utf-8")
        fh.setFormatter(_JsonFormatter())
        logger.addHandler(fh)
    logger.propagate = False
    return logger


# Emit a structured event with extra key/value fields.
def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"extra_fields": {"event": event, **fields}})


# ---------------------------------------------------------------------------
# Filename / snapshot helpers
# ---------------------------------------------------------------------------
# Pull the snapshot date out of a filename using a regex + date format.
def parse_snapshot_date(filename: str, pattern: str, date_format: str) -> datetime:
    match = re.search(pattern, filename)
    if not match:
        raise ValueError(f"Cannot parse snapshot date from filename: {filename!r}")
    return datetime.strptime(match.group(1), date_format)


# Return all credit CSV files sorted in filename order.
def list_credit_files(paths: Paths) -> list[Path]:
    if not paths.raw_credit_dir.exists():
        return []
    return sorted(paths.raw_credit_dir.glob(paths.raw_credit_glob))


# ---------------------------------------------------------------------------
# Alerting hook (deliberately a no-op outside production; logs intent)
# ---------------------------------------------------------------------------
# Log an alert and pick the channels (email/Slack/PagerDuty) by severity.
def dispatch_alert(
    logger: logging.Logger,
    cfg: dict[str, Any],
    *,
    severity: str,
    title: str,
    body: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Routes a single alert across configured channels by severity.

    In a production deployment this would call the channel SDKs (smtplib,
    Slack webhook, PagerDuty Events API). Here we log the intent so that
    the routing decision is auditable from the JSONL log stream and the
    same code can be wired to live endpoints by setting the env vars
    declared in pipeline.yaml.
    """
    severity = severity.upper()
    routing = cfg.get("alerting", {}).get("severity_routing", {})
    channels = routing.get(severity, [])
    log_event(
        logger,
        "alert_dispatched",
        severity=severity,
        title=title,
        body=body,
        channels=list(channels),
        context=context or {},
    )


# ---------------------------------------------------------------------------
# Pandas IO helpers
# ---------------------------------------------------------------------------
# Write a DataFrame to Parquet, creating parent dirs as needed.
def write_parquet(df, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


# Write a DataFrame to CSV, creating parent dirs as needed.
def write_csv(df, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
# Context manager that logs the start, end, and duration of a step.
@contextmanager
def timed(logger: logging.Logger, label: str):
    start = datetime.utcnow()
    log_event(logger, "step_start", step=label)
    try:
        yield
    finally:
        duration = (datetime.utcnow() - start).total_seconds()
        log_event(logger, "step_end", step=label, duration_seconds=duration)


# Yield successive lists of `size` items from any iterable.
def chunked(it: Iterable, size: int):
    bucket = []
    for item in it:
        bucket.append(item)
        if len(bucket) == size:
            yield bucket
            bucket = []
    # Emit the remaining items if the last bucket is partial.
    if bucket:
        yield bucket
