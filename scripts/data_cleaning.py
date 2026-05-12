"""Clean & standardize the three source domains into staging Parquet.

This module is intentionally pure: every transform is a small, testable
function with no I/O side effects beyond the final `write_parquet` step in
`main()`. That keeps the unit tests in `tests/test_pipeline.py` simple and
keeps the public functions reusable from the orchestrator or a notebook.

Cleaning rules (all decisions documented inline):

  1. Column names -> snake_case, trimmed of whitespace.
  2. Drop fully-empty padding rows that Excel emits for "used range" sheets.
  3. Strip the schema-drift columns from later credit snapshots
     ("Unnamed: 28" was a 100%-null garbage column).
  4. Parse every date column with mixed format support.
  5. Deduplicate using a deterministic key (loan_id+snapshot for credit,
     loan_id for customer master, submission_id for NPS).
  6. Fix NPS Mojibake (U+FFFD replacement char) in column headers.

Output layout:

  data/staging/credit_snapshots.parquet   (union of all snapshot CSVs)
  data/staging/customers.parquet          (unified customer master, one row per loan_id)
  data/staging/sales.parquet              (sales facts, one row per sale_id/loan_id)
  data/staging/nps.parquet                (NPS facts, one row per submission_id)
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

import pandas as pd

from utils import (
    ensure_dirs,
    get_logger,
    list_credit_files,
    load_config,
    log_event,
    parse_snapshot_date,
    resolve_paths,
    timed,
    write_parquet,
)


# Canonical date columns expected in credit snapshots.
DATE_COLUMNS_CREDIT = {
    "date",
    "sale_date",
    "return_date",
    "credit_expiry",
    "next_invoice_date",
    "max_payment_date",
}


# ---------------------------------------------------------------------------
# Header normalisation
# ---------------------------------------------------------------------------
# Clean a single column header into snake_case.
def _normalise_header(name: str) -> str:
    """Trim, replace mojibake, collapse whitespace, snake_case."""
    if name is None:
        return ""
    n = str(name).strip()
    # Remove mojibake / replacement characters often emitted by older Excel files
    n = n.replace("�", "").replace(" ", " ")
    # Normalise unicode form, drop punctuation, collapse whitespace to underscores.
    n = unicodedata.normalize("NFKD", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", "_", n).strip("_").lower()
    return n


# Apply header normalisation to every column and drop padding columns.
def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalise_header(c) for c in df.columns]
    # Drop columns whose normalised name is empty (rare, but possible)
    df = df.loc[:, [c for c in df.columns if c]]
    # Drop columns that came in as "unnamed_<N>" (Excel padding / schema drift)
    df = df.loc[:, [c for c in df.columns if not c.startswith("unnamed_")]]
    return df


# ---------------------------------------------------------------------------
# Empty-row handling for Excel "used range" padding
# ---------------------------------------------------------------------------
# Drop rows that are blank or have no key column values.
def drop_empty_rows(df: pd.DataFrame, *, key_cols: Iterable[str] | None = None) -> pd.DataFrame:
    """Drop rows that are entirely NaN, or - if key_cols supplied - rows where
    every key column is NaN. Used to strip Excel's blank trailing rows.
    """
    # If key columns are given, keep rows where at least one is non-null.
    if key_cols:
        existing = [c for c in key_cols if c in df.columns]
        if existing:
            mask = df[existing].notna().any(axis=1)
            return df.loc[mask].copy()
    # Otherwise drop rows that are NaN across every column.
    return df.dropna(how="all").copy()


# ---------------------------------------------------------------------------
# Date parsing with multi-format support
# ---------------------------------------------------------------------------
# Parse listed columns to datetime, handling mixed formats and timezones.
def parse_dates(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            continue
        s = df[col]
        # If already datetime, just strip any timezone.
        if pd.api.types.is_datetime64_any_dtype(s):
            df[col] = pd.to_datetime(s, errors="coerce").dt.tz_localize(None)
            continue
        # First pass: month-first parsing.
        parsed = pd.to_datetime(s.astype("string"), errors="coerce", format="mixed", dayfirst=False)
        # Retry the rows that failed using day-first format (e.g. "30-06-2025").
        bad = parsed.isna() & s.notna()
        if bad.any():
            retry = pd.to_datetime(s.where(bad).astype("string"), errors="coerce",
                                   format="mixed", dayfirst=True)
            parsed = parsed.where(~bad, retry)
        # Drop timezone info (e.g. Africa/Nairobi on some DOB rows).
        if hasattr(parsed.dtype, "tz") and parsed.dtype.tz is not None:
            parsed = parsed.dt.tz_localize(None)
        df[col] = parsed
    return df


# ---------------------------------------------------------------------------
# Domain-specific cleaners
# ---------------------------------------------------------------------------
# Clean a single credit snapshot: types, renames, dedupe.
def clean_credit_snapshot(df: pd.DataFrame, *, snapshot_date) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["loan_id"])

    # Parse all known date columns.
    df = parse_dates(df, DATE_COLUMNS_CREDIT)

    # Stamp the snapshot date from the filename (trusted source).
    df["snapshot_date"] = pd.to_datetime(snapshot_date).normalize()

    # `customer_age` in the source is actually days-since-sale; rename it.
    if "customer_age" in df.columns:
        df = df.rename(columns={"customer_age": "loan_age_days"})

    # Trim whitespace on categorical string columns.
    for c in ["balance_due_status", "account_status_l1", "account_status_l2",
              "credit_check_done"]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()

    # Coerce financial / numeric columns to numbers.
    for c in ["balance", "arrears", "days_past_due", "total_paid",
              "total_due_today", "closing_balance", "balance_due_to_date",
              "weekly_rate", "deposit", "discount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Deduplicate on (loan_id, snapshot_date), keeping the freshest max_payment_date.
    if "loan_id" in df.columns:
        sort_cols = ["snapshot_date", "loan_id"]
        if "max_payment_date" in df.columns:
            sort_cols.append("max_payment_date")
        df = df.sort_values(sort_cols, na_position="first")
        df = df.drop_duplicates(subset=["loan_id", "snapshot_date"], keep="last")

    return df.reset_index(drop=True)


# Clean the Sales Details sheet (product + price info per sale).
def clean_sales_details(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["sale_id", "loan_id"])
    df = parse_dates(df, ["sale_date", "return_date"])
    # Coerce price columns to numbers.
    for c in ["cash_price", "loan_price"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Cast the returned flag to nullable boolean.
    if "returned" in df.columns:
        df["returned"] = df["returned"].astype("boolean")
    # Trim string categoricals.
    for c in ["seller", "seller_type", "sale_type", "product_name", "model",
              "business_model", "client_model", "loan_term"]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    # Keep the most recent sale per loan_id.
    if "loan_id" in df.columns:
        df = df.sort_values(["loan_id", "sale_date"], na_position="first")
        df = df.drop_duplicates(subset=["loan_id"], keep="last")
    return df.reset_index(drop=True)


# Clean the Gender sheet (citizenship + gender per loan_id).
def clean_sales_gender(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["loan_id"])
    # Standardise text to Title Case.
    for c in ["citizenship", "gender"]:
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip().str.title()
    if "loan_id" in df.columns:
        df = df.drop_duplicates(subset=["loan_id"], keep="last")
    return df.reset_index(drop=True)


# Clean the DOB sheet (date-of-birth per loan_id).
def clean_sales_dob(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["loan_id"])
    df = parse_dates(df, ["date_of_birth", "createdat_utc"])
    # Keep the latest DOB record per loan.
    if "loan_id" in df.columns:
        df = df.sort_values(["loan_id", "createdat_utc"], na_position="first")
        df = df.drop_duplicates(subset=["loan_id"], keep="last")
    return df.reset_index(drop=True)


# Clean the Income Level sheet (income panel per loan_id).
def clean_sales_income(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["loan_id"])
    # Coerce income / count columns to numeric.
    for c in ["duration", "received", "persons_received_from_total",
              "banks_received", "paybills_received_others"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Keep the row with the largest `received` per loan.
    if "loan_id" in df.columns:
        df = df.sort_values(["loan_id", "received"], na_position="first")
        df = df.drop_duplicates(subset=["loan_id"], keep="last")
    return df.reset_index(drop=True)


# Clean the NPS survey responses (one row per submission).
def clean_nps(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    df = drop_empty_rows(df, key_cols=["submission_id", "loan_id"])
    # Rename the verbose NPS question column to `nps_score`.
    long_q = next((c for c in df.columns if c.startswith("using_a_scale_from_0")), None)
    if long_q:
        df = df.rename(columns={long_q: "nps_score"})
    df = parse_dates(df, ["submitted_at"])
    # Derive the NPS bucket (Detractor / Passive / Promoter) from the score.
    if "nps_score" in df.columns:
        df["nps_score"] = pd.to_numeric(df["nps_score"], errors="coerce")
        df["nps_bucket"] = pd.cut(
            df["nps_score"],
            bins=[-1, 6, 8, 10],
            labels=["Detractor", "Passive", "Promoter"],
        ).astype("string")
    # Drop duplicate submissions.
    if "submission_id" in df.columns:
        df = df.drop_duplicates(subset=["submission_id"], keep="last")

    # Force all object columns to nullable string for Parquet stability.
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype("string")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
# Clean every credit snapshot CSV and concat into one DataFrame.
def clean_all_credit(paths, cfg, logger) -> pd.DataFrame:
    pattern = cfg["ingest"]["filename_date_pattern"]
    fmt = cfg["ingest"]["filename_date_format"]
    frames: list[pd.DataFrame] = []
    # Read and clean each snapshot file in turn.
    for f in list_credit_files(paths):
        snap = parse_snapshot_date(f.name, pattern, fmt).date()
        raw = pd.read_csv(f, **cfg["ingest"]["csv_read"])
        cleaned = clean_credit_snapshot(raw, snapshot_date=snap)
        log_event(logger, "clean_credit", file=f.name, snapshot=str(snap),
                  in_rows=len(raw), out_rows=len(cleaned),
                  columns=len(cleaned.columns))
        frames.append(cleaned)
    if not frames:
        raise FileNotFoundError("No credit files to clean")
    # Align columns across snapshots before concatenation.
    union = sorted({c for f in frames for c in f.columns})
    frames = [f.reindex(columns=union) for f in frames]
    return pd.concat(frames, ignore_index=True)


# Clean each sales sheet (Sales Details / Gender / DOB / Income Level).
def clean_customer_master(paths, logger) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    xl = pd.ExcelFile(paths.raw_sales_xlsx)
    out: dict[str, pd.DataFrame] = {}
    # Apply the right cleaner to each known sheet.
    for sheet, cleaner in (
        ("Sales Details", clean_sales_details),
        ("Gender",        clean_sales_gender),
        ("DOB",           clean_sales_dob),
        ("Income Level",  clean_sales_income),
    ):
        raw = pd.read_excel(paths.raw_sales_xlsx, sheet_name=sheet)
        cleaned = cleaner(raw)
        log_event(logger, "clean_sales_sheet", sheet=sheet,
                  in_rows=len(raw), out_rows=len(cleaned))
        out[sheet] = cleaned
    return out["Sales Details"], out["Gender"], out["DOB"], out["Income Level"]


# Read + clean the NPS Excel file.
def clean_nps_dataset(paths, logger) -> pd.DataFrame:
    raw = pd.read_excel(paths.raw_nps_xlsx)
    cleaned = clean_nps(raw)
    log_event(logger, "clean_nps", in_rows=len(raw), out_rows=len(cleaned))
    return cleaned


# Join all customer attribute sheets onto the sales backbone.
def build_customer_master(sales, gender, dob, income) -> pd.DataFrame:
    """Left-join all customer attributes around the sales backbone."""
    base = sales[[c for c in sales.columns if c != "return_date"]].copy()
    # Merge gender, DOB and income panel by loan_id.
    out = base.merge(gender[["loan_id", "citizenship", "gender"]],
                     on="loan_id", how="left", validate="one_to_one") \
              .merge(dob[["loan_id", "date_of_birth"]],
                     on="loan_id", how="left", validate="one_to_one") \
              .merge(income[["loan_id", "duration", "received",
                             "persons_received_from_total", "banks_received",
                             "paybills_received_others"]],
                     on="loan_id", how="left", validate="one_to_one")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# CLI entrypoint: read raw data, clean it, write Parquet staging files.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args.
    parser = argparse.ArgumentParser(description="Clean & stage raw data to Parquet")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    # Load config + set up directories and logger.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("cleaning", paths.logs)

    # Stage credit snapshots.
    with timed(logger, "credit_snapshots"):
        credit = clean_all_credit(paths, cfg, logger)
        write_parquet(credit, paths.staging / "credit_snapshots.parquet")

    # Stage customer master + sales fact.
    with timed(logger, "customers"):
        sales, gender, dob, income = clean_customer_master(paths, logger)
        customers = build_customer_master(sales, gender, dob, income)
        write_parquet(customers, paths.staging / "customers.parquet")
        write_parquet(sales,     paths.staging / "sales.parquet")

    # Stage NPS responses.
    with timed(logger, "nps"):
        nps = clean_nps_dataset(paths, logger)
        write_parquet(nps, paths.staging / "nps.parquet")

    log_event(logger, "cleaning_complete",
              credit_rows=len(credit),
              customer_rows=len(customers),
              nps_rows=len(nps))
    print(f"OK  staged credit={len(credit):,}  customers={len(customers):,}  nps={len(nps):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
