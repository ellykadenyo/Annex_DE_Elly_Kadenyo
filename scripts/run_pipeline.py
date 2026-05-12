"""End-to-end pipeline runner.

Runs the full ELT in a single command:

    profile -> clean -> features -> warehouse -> quality -> analysis

This is the single entry point for both local reproducibility (`make run`)
and a scheduled job (cron / Airflow PythonOperator). Each stage is invoked
as an in-process function so the orchestrator can short-circuit on failure
and surface a single exit code.

CLI:
    python scripts/run_pipeline.py             # full run
    python scripts/run_pipeline.py --skip-profile --skip-warehouse-fresh

Exit codes:
    0  success
    1  unrecoverable error in any stage
    2  data quality check FAILED (when --fail-on-dq is set)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import data_cleaning
import data_profiling
import feature_engineering
import build_warehouse
import quality_checks
import analysis

from utils import (
    ensure_dirs,
    get_logger,
    load_config,
    log_event,
    resolve_paths,
    timed,
)


# Stages executed in pipeline order.
STAGES = [
    "profile",
    "clean",
    "features",
    "warehouse",
    "quality",
    "analysis",
]


# CLI entrypoint: orchestrate every pipeline stage in order.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args (with skip/only/fresh flags).
    parser = argparse.ArgumentParser(description="Run the full ABC Phones pipeline")
    parser.add_argument("--config", default=None)
    parser.add_argument("--skip", nargs="*", choices=STAGES, default=[],
                        help="Skip one or more stages")
    parser.add_argument("--only", nargs="*", choices=STAGES, default=None,
                        help="Run only the listed stages (in order)")
    parser.add_argument("--warehouse-fresh", action="store_true",
                        help="Drop & recreate the DuckDB file")
    parser.add_argument("--fail-on-dq", action="store_true",
                        help="Exit non-zero if any DQ check fails")
    args = parser.parse_args(argv)

    # Load config + set up directories.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)

    # Set a single run_id used in all log filenames.
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    os.environ["PIPELINE_RUN_ID"] = run_id
    logger = get_logger("orchestrator", paths.logs)
    log_event(logger, "pipeline_start", run_id=run_id, skip=args.skip, only=args.only)

    # Resolve which stages to run.
    selected = args.only if args.only else [s for s in STAGES if s not in args.skip]

    try:
        # Stage 1: profile raw inputs.
        if "profile" in selected:
            with timed(logger, "stage_profile"):
                rc = data_profiling.main(["--config", args.config] if args.config else [])
                if rc != 0:
                    raise SystemExit("profile stage failed")

        # Stage 2: clean + stage Parquet.
        if "clean" in selected:
            with timed(logger, "stage_clean"):
                rc = data_cleaning.main(["--config", args.config] if args.config else [])
                if rc != 0:
                    raise SystemExit("clean stage failed")

        # Stage 3: derive analytics features.
        if "features" in selected:
            with timed(logger, "stage_features"):
                rc = feature_engineering.main(["--config", args.config] if args.config else [])
                if rc != 0:
                    raise SystemExit("features stage failed")

        # Stage 4: load the DuckDB warehouse.
        if "warehouse" in selected:
            wh_args = ["--config", args.config] if args.config else []
            if args.warehouse_fresh:
                wh_args.append("--fresh")
            with timed(logger, "stage_warehouse"):
                rc = build_warehouse.main(wh_args)
                if rc != 0:
                    raise SystemExit("warehouse stage failed")

        # Stage 5: run data-quality checks.
        if "quality" in selected:
            dq_args = ["--config", args.config] if args.config else []
            if args.fail_on_dq:
                dq_args.append("--fail-on-fail")
            with timed(logger, "stage_quality"):
                rc = quality_checks.main(dq_args)
                # rc == 2 means a DQ check failed but the stage itself ran fine.
                if rc not in (0, 2):
                    raise SystemExit("quality stage failed")
                if rc == 2 and args.fail_on_dq:
                    log_event(logger, "pipeline_dq_failure", run_id=run_id)
                    return 2

        # Stage 6: portfolio analysis + charts + insights.
        if "analysis" in selected:
            with timed(logger, "stage_analysis"):
                rc = analysis.main(["--config", args.config] if args.config else [])
                if rc != 0:
                    raise SystemExit("analysis stage failed")

    except SystemExit as e:
        # Any stage error short-circuits the run.
        log_event(logger, "pipeline_failure", run_id=run_id, error=str(e))
        print(f"FAIL  pipeline aborted: {e}", file=sys.stderr)
        return 1

    log_event(logger, "pipeline_success", run_id=run_id)
    print(f"OK  pipeline complete (run_id={run_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
