"""Load curated parquet into a DuckDB warehouse.

DuckDB was chosen as the local analytical store because it:
  - has zero infrastructure overhead (file-based, embedded)
  - reads parquet natively without copying data
  - speaks ANSI SQL, so the same queries run against Postgres/Snowflake later
  - is fully open-source (MIT)

Tables created:
  fct_portfolio_snapshot     - 1 row per (loan_id, snapshot_date) with features
  dim_customer               - 1 row per loan_id, customer attributes
  fct_sales                  - 1 row per sale
  fct_nps                    - 1 row per NPS submission

Views created:
  v_portfolio_health           - delinquency / loss / collection KPIs by snapshot
  v_portfolio_by_age_band      - same KPIs sliced by age band
  v_portfolio_by_income_band   - same KPIs sliced by income band
  v_portfolio_by_risk          - risk-category mix per snapshot
  v_credit_x_nps               - credit performance joined to NPS responses

Partitioning strategy (logical, since DuckDB is a single file):
  All facts include `snapshot_date` (credit) / `submitted_at` (nps) / `sale_date`
  (sales) so analysts can prune by date.  When the volumes grow large enough
  to outlive a single file, the same SQL works against partitioned Parquet
  on object storage (s3://.../dt=YYYY-MM-DD/).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

from utils import (
    ANNEX_ROOT,
    ensure_dirs,
    get_logger,
    load_config,
    log_event,
    resolve_paths,
    timed,
)


SQL_DIR = ANNEX_ROOT / "sql"


def _exec_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    con.execute(sql)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the DuckDB warehouse")
    parser.add_argument("--config", default=None)
    parser.add_argument("--fresh", action="store_true",
                        help="Drop and recreate the warehouse file")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("warehouse", paths.logs)

    if args.fresh and paths.warehouse.exists():
        paths.warehouse.unlink()
        log_event(logger, "warehouse_dropped", path=str(paths.warehouse))

    con = duckdb.connect(str(paths.warehouse))

    with timed(logger, "load_tables"):
        portfolio = (paths.curated / "portfolio_features.parquet").resolve().as_posix()
        customers = (paths.staging / "customers.parquet").resolve().as_posix()
        sales     = (paths.staging / "sales.parquet").resolve().as_posix()
        nps       = (paths.staging / "nps.parquet").resolve().as_posix()

        con.execute(
            f"""
            CREATE OR REPLACE TABLE fct_portfolio_snapshot AS
            SELECT * FROM read_parquet('{portfolio}');
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE dim_customer AS
            SELECT * FROM read_parquet('{customers}');
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE fct_sales AS
            SELECT * FROM read_parquet('{sales}');
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE fct_nps AS
            SELECT * FROM read_parquet('{nps}');
            """
        )

    with timed(logger, "create_views"):
        for sql_file in sorted(SQL_DIR.glob("view_*.sql")):
            _exec_file(con, sql_file)
            log_event(logger, "view_created", file=sql_file.name)

    # Quick row-count summary for the run log
    counts = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("fct_portfolio_snapshot", "dim_customer", "fct_sales", "fct_nps")
    }
    log_event(logger, "warehouse_built", warehouse=str(paths.warehouse),
              row_counts=counts)
    print(f"OK  warehouse -> {paths.warehouse} | {counts}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
