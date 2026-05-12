"""Feature engineering on top of the staged data.

Derives the four required features from the case study brief:

  age_band                - banded age in years computed from DOB at each
                            reporting (snapshot) date
  avg_monthly_income_band - monthly income inferred from the income panel:
                              sum(received + banks_received + paybills_received_others)
                            divided by employment-/income-window duration in
                            months ("Duration" column)
  days_past_due           - taken from credit snapshot, clipped at 0 for the
                            "no arrears" case
  risk_category           - tiered classification: Low / Medium / High / Critical
                            driven by account_status_l1, account_status_l2,
                            days_past_due, arrears (rule order in config)

Joins (left, around the credit snapshot fact):
  credit_snapshots  *--1  customers (loan_id)
  customers contains: gender, citizenship, sale_date, date_of_birth,
                      duration, received, banks_received, paybills_received_others

Output:
  data/curated/portfolio_features.parquet   (1 row per loan_id per snapshot)
  outputs/cleaned_summary.csv               (representative sample, 5k rows)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from utils import (
    ensure_dirs,
    get_logger,
    load_config,
    log_event,
    resolve_paths,
    timed,
    write_csv,
    write_parquet,
)


# ---------------------------------------------------------------------------
# Age & income derivation
# ---------------------------------------------------------------------------
# Compute age in years between DOB and a reference date.
def compute_age_years(dob: pd.Series, ref: pd.Series) -> pd.Series:
    """Years between DOB and the reporting date, using floor (true completed years)."""
    dob = pd.to_datetime(dob, errors="coerce")
    ref = pd.to_datetime(ref, errors="coerce")
    diff = (ref - dob).dt.days / 365.25
    # Reject impossible ages (negative or > 130).
    return diff.where(diff.between(0, 130)).astype("Float64")


# Assign each numeric value to a labelled band defined as [min, max).
def band(series: pd.Series, bands: Iterable[dict[str, Any]]) -> pd.Series:
    """Bucket numeric series into labelled bands defined as [min, max)."""
    bands = list(bands)
    out = pd.Series(pd.NA, index=series.index, dtype="string")
    # Apply each band spec in order; later matches overwrite earlier ones.
    for spec in bands:
        lo = spec["min"]
        hi = spec["max"]
        mask = series.notna()
        if lo is not None:
            mask &= series >= lo
        if hi is not None:
            mask &= series < hi
        out = out.mask(mask, spec["label"])
    return out


# Estimate average monthly income from the customer income panel.
def compute_monthly_income(customers: pd.DataFrame) -> pd.Series:
    """Average monthly income.

    Formula (per the brief): sum all income-related columns, divide by
    employment duration. Here the income panel stores `received` as the
    aggregate inflow over `duration` months, with `banks_received` and
    `paybills_received_others` as channel sub-totals already included
    inside `received`. Using `received / duration` therefore matches the
    spec without double-counting.

    Where `duration` is missing or zero, falls back to `NaN` so the band
    becomes NULL rather than silently mis-classifying the customer.
    """
    # Pull the inflow + duration columns and coerce to numeric.
    received = pd.to_numeric(customers.get("received"), errors="coerce")
    duration = pd.to_numeric(customers.get("duration"), errors="coerce")
    # Avoid divide-by-zero: treat 0/missing duration as NaN.
    duration = duration.where(duration > 0)
    return (received / duration).astype("Float64")


# ---------------------------------------------------------------------------
# Risk category
# ---------------------------------------------------------------------------
# Tag each loan with a risk_category by applying tiered rules first-match-wins.
def classify_risk(df: pd.DataFrame, rules: list[dict[str, Any]]) -> pd.Series:
    """Apply tiered rules first-match-wins to derive risk_category."""
    out = pd.Series(pd.NA, index=df.index, dtype="string")
    # Track rows still awaiting a classification.
    remaining = pd.Series(True, index=df.index)
    # Walk each rule in priority order.
    for rule in rules:
        if not remaining.any():
            break
        # Default rule: assign label to all remaining rows and stop.
        if rule.get("default"):
            out = out.mask(remaining, rule["name"])
            remaining[:] = False
            break
        # Build the match mask from the rule's conditions.
        mask = pd.Series(False, index=df.index)
        if "account_status_l1_in" in rule and "account_status_l1" in df.columns:
            mask = mask | df["account_status_l1"].isin(rule["account_status_l1_in"])
        if "account_status_l2_in" in rule and "account_status_l2" in df.columns:
            mask = mask | df["account_status_l2"].isin(rule["account_status_l2_in"])
        if "days_past_due_min" in rule and "days_past_due" in df.columns:
            mask = mask | (df["days_past_due"].fillna(0) >= rule["days_past_due_min"])
        # Only assign rows not yet classified.
        mask = mask & remaining
        out = out.mask(mask, rule["name"])
        remaining = remaining & ~mask
    # Fallback for any leftover rows.
    out = out.fillna("Low")
    return out


# ---------------------------------------------------------------------------
# Composition: build the curated portfolio features table
# ---------------------------------------------------------------------------
# Customer attribute columns brought in from the customer master.
CUSTOMER_JOIN_COLS = [
    "loan_id", "sale_id", "sale_date", "sale_type", "seller", "seller_type",
    "product_name", "model", "loan_term", "business_model", "client_model",
    "cash_price", "loan_price", "returned",
    "citizenship", "gender", "date_of_birth",
    "duration", "received", "persons_received_from_total",
    "banks_received", "paybills_received_others",
]


# Join customer attributes onto credit snapshots and derive analytics features.
def build_feature_table(credit: pd.DataFrame, customers: pd.DataFrame,
                        cfg: dict[str, Any]) -> pd.DataFrame:
    # Merge customer fields onto each credit snapshot row.
    join_cols = [c for c in CUSTOMER_JOIN_COLS if c in customers.columns]
    df = credit.merge(customers[join_cols], on="loan_id", how="left", validate="many_to_one")

    # 1. Compute age in years at each snapshot and bucket into bands.
    df["customer_age_years"] = compute_age_years(df["date_of_birth"], df["snapshot_date"])
    df["age_band"] = band(df["customer_age_years"], cfg["feature_engineering"]["age_bands"])

    # 2. Compute monthly income and bucket into income bands.
    df["avg_monthly_income"] = compute_monthly_income(df)
    df["avg_monthly_income_band"] = band(df["avg_monthly_income"],
                                         cfg["feature_engineering"]["income_bands"])

    # 3. Clean days_past_due: numeric, non-negative, integer.
    df["days_past_due"] = pd.to_numeric(df.get("days_past_due"), errors="coerce").fillna(0).clip(lower=0).astype("Int64")

    # 4. Classify each loan into a risk category.
    df["risk_category"] = classify_risk(df, cfg["feature_engineering"]["risk_category"]["rules"])

    # Derived boolean flags useful for downstream aggregations.
    df["is_delinquent"] = (df["days_past_due"] > 0).astype("Int8")
    df["is_write_off"]  = df["account_status_l1"].str.contains("write off|write_off",
                                                               case=False, na=False).astype("Int8")
    df["is_returned"]   = df["account_status_l1"].str.contains("return",
                                                               case=False, na=False).astype("Int8")
    df["is_paid_off"]   = df["account_status_l1"].str.contains("paid off|paid_off",
                                                               case=False, na=False).astype("Int8")

    # Put the most-used columns first for readability.
    leading = ["loan_id", "snapshot_date", "sale_date", "date_of_birth",
               "customer_age_years", "age_band",
               "avg_monthly_income", "avg_monthly_income_band",
               "days_past_due", "arrears", "balance", "closing_balance",
               "account_status_l1", "account_status_l2",
               "risk_category", "is_delinquent", "is_write_off",
               "is_returned", "is_paid_off"]
    rest = [c for c in df.columns if c not in leading]
    return df[[c for c in leading if c in df.columns] + rest]


# CLI entrypoint: build the curated feature table and a sample CSV.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args.
    parser = argparse.ArgumentParser(description="Derive analytics features")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    # Load config + set up directories and logger.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("features", paths.logs)

    # Load the staged inputs.
    with timed(logger, "load_staging"):
        credit = pd.read_parquet(paths.staging / "credit_snapshots.parquet")
        customers = pd.read_parquet(paths.staging / "customers.parquet")
        log_event(logger, "loaded_staging", credit_rows=len(credit),
                  customer_rows=len(customers))

    # Build the curated feature table and write a sample CSV.
    with timed(logger, "build_features"):
        features = build_feature_table(credit, customers, cfg)
        write_parquet(features, paths.curated / "portfolio_features.parquet")
        # Write a deterministic 5k-row sample for human inspection.
        sample_n = min(5000, len(features))
        sample = features.sample(n=sample_n, random_state=42).sort_values(
            ["snapshot_date", "loan_id"]
        )
        write_csv(sample, paths.outputs / "cleaned_summary.csv")

    risk_dist = features["risk_category"].value_counts(dropna=False).to_dict()
    age_match_rate = features["age_band"].notna().mean()
    income_match_rate = features["avg_monthly_income_band"].notna().mean()
    log_event(logger, "feature_complete",
              rows=len(features),
              risk_distribution={str(k): int(v) for k, v in risk_dist.items()},
              age_band_coverage=round(float(age_match_rate), 3),
              income_band_coverage=round(float(income_match_rate), 3))
    print(f"OK  features={len(features):,}  risk={risk_dist}  "
          f"age_band%={age_match_rate:.1%}  income_band%={income_match_rate:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
