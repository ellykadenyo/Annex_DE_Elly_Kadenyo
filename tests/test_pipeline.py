"""Unit tests for the pure-function transforms.

These never read source files - they exercise the cleaning, banding and
risk-classification logic with hand-crafted fixtures so they stay fast and
robust to source data changes.

Run with: `pytest tests -q`
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest


# Make scripts/ importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import data_cleaning as dc  # noqa: E402
import feature_engineering as fe  # noqa: E402
import quality_checks as qc  # noqa: E402


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
# Headers should be trimmed, lowercased, and mojibake stripped.
def test_normalise_columns_strips_whitespace_and_mojibake():
    df = pd.DataFrame(columns=["Loan Id ", "  Email ", "Score?", "(If Yes) �Q"])
    out = dc.normalise_columns(df)
    assert list(out.columns) == ["loan_id", "email", "score", "if_yes_q"]


# Excel padding columns named "Unnamed: <N>" should be dropped.
def test_normalise_columns_drops_unnamed_padding():
    df = pd.DataFrame(columns=["loan_id", "Unnamed: 28", "balance"])
    out = dc.normalise_columns(df)
    assert "unnamed_28" not in out.columns
    assert set(out.columns) == {"loan_id", "balance"}


# Rows where all key columns are NaN should be dropped.
def test_drop_empty_rows_by_key():
    df = pd.DataFrame({
        "loan_id": ["A", None, "B", None],
        "value":   [1, None, 2, None],
    })
    out = dc.drop_empty_rows(df, key_cols=["loan_id"])
    assert list(out["loan_id"]) == ["A", "B"]


# Both month-first and day-first date strings should parse correctly.
def test_parse_dates_handles_mixed_format():
    df = pd.DataFrame({"date": ["1/2/2025", "30-06-2025", None]})
    out = dc.parse_dates(df, ["date"])
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert out["date"].iloc[0] == pd.Timestamp("2025-01-02")
    assert out["date"].iloc[1] == pd.Timestamp("2025-06-30")
    assert pd.isna(out["date"].iloc[2])


# Duplicate (loan_id, snapshot_date) rows should collapse to one.
def test_clean_credit_snapshot_dedupes_on_pk():
    df = pd.DataFrame({
        "LOAN_ID":           ["L1", "L1", "L2"],
        "DATE":              ["1/1/2025"] * 3,
        "MAX_PAYMENT_DATE":  ["1/5/2025", "1/10/2025", "1/3/2025"],
        "ARREARS":           [10, 0, 5],
        "ACCOUNT_STATUS_L1": ["X", "X", "Y"],
        "ACCOUNT_STATUS_L2": ["A", "A", "B"],
        "CUSTOMER_AGE":      [120, 130, 90],
        "DAYS_PAST_DUE":     [0, 0, 5],
    })
    out = dc.clean_credit_snapshot(df, snapshot_date="2025-01-01")
    # Should dedupe to L1 (latest max_payment_date) + L2
    assert len(out) == 2
    assert "loan_age_days" in out.columns  # CUSTOMER_AGE renamed
    l1 = out[out["loan_id"] == "L1"].iloc[0]
    assert l1["arrears"] == 0  # the row with later MAX_PAYMENT_DATE wins


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
# Negative or > 130 year ages should be returned as NaN.
def test_compute_age_years_rejects_impossible():
    dob = pd.Series([datetime(1990, 1, 1), datetime(2050, 1, 1), None])
    ref = pd.Series([datetime(2025, 1, 1)] * 3)
    out = fe.compute_age_years(dob, ref)
    assert float(out.iloc[0]) == pytest.approx(35.0, abs=0.1)
    assert pd.isna(out.iloc[1])  # future DOB ignored
    assert pd.isna(out.iloc[2])


# Bands use [min, max) semantics: lower inclusive, upper exclusive.
def test_band_uses_inclusive_lower_exclusive_upper():
    bands = [
        {"label": "18-25", "min": 18, "max": 26},
        {"label": "26-35", "min": 26, "max": 36},
        {"label": "55+",   "min": 56, "max": None},
    ]
    out = fe.band(pd.Series([17, 18, 25, 26, 56, 99]), bands)
    # First value (17) falls outside all bands => NA. Compare via fillna for clarity.
    assert list(out.fillna("MISSING")) == ["MISSING", "18-25", "18-25", "26-35", "55+", "55+"]


# Risk rules apply in priority order; the first matching rule wins.
def test_classify_risk_first_match_wins():
    rules = [
        {"name": "Critical", "account_status_l1_in": ["Write Off"]},
        {"name": "High",     "days_past_due_min": 30},
        {"name": "Low",      "default": True},
    ]
    df = pd.DataFrame({
        "account_status_l1": ["Write Off", "Active", "Active"],
        "account_status_l2": [None, "PAR 7", "Active"],
        "days_past_due":     [0, 45, 0],
    })
    out = fe.classify_risk(df, rules)
    assert list(out) == ["Critical", "High", "Low"]


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------
# Uniqueness check should fail and dump evidence when duplicates exist.
def test_uniqueness_check_fails_on_duplicates(tmp_path):
    df = pd.DataFrame({
        "loan_id":       ["A", "A", "B"],
        "snapshot_date": [pd.Timestamp("2025-01-01")] * 3,
    })
    paths = type("P", (), {"outputs": tmp_path})()
    r = qc.check_uniqueness(df, paths)
    assert r.status == "FAIL"
    assert (tmp_path / "dq_duplicates.csv").exists()


# Uniqueness check should pass when the key is unique.
def test_uniqueness_check_passes_on_clean_data(tmp_path):
    df = pd.DataFrame({
        "loan_id":       ["A", "B"],
        "snapshot_date": [pd.Timestamp("2025-01-01")] * 2,
    })
    paths = type("P", (), {"outputs": tmp_path})()
    r = qc.check_uniqueness(df, paths)
    assert r.status == "PASS"


# Range check should flag ages outside the [min, max] window.
def test_range_age_flags_outliers():
    df = pd.DataFrame({"customer_age_years": [25.0, 200.0, 15.0, None]})
    cfg = {"quality": {"ranges": {"age_min": 18, "age_max": 100}}}
    r = qc.check_range_customer_age(df, cfg)
    assert r.status == "FAIL"
    assert "2" in r.observed   # 2 rows out of range
