-- =============================================================================
-- Data Quality Checks (SQL companion to scripts/quality_checks.py).
-- Run against the DuckDB warehouse with:
--     duckdb data/warehouse/abc_phones.duckdb < sql/quality_checks.sql
-- Every check returns one row with: check_name, status, expected, observed.
-- Combine them with `UNION ALL` for a single DQ dashboard query.
-- =============================================================================

-- 1. FRESHNESS: latest snapshot must be no more than 100 days old.
WITH latest AS (
    SELECT MAX(snapshot_date) AS latest_snap FROM fct_portfolio_snapshot
)
SELECT
    'FRESHNESS' AS check_name,
    CASE WHEN DATE_DIFF('day', latest_snap, CURRENT_DATE) <= 100 THEN 'PASS' ELSE 'FAIL' END AS status,
    'latest snapshot age <= 100d' AS expected,
    'latest=' || latest_snap || ', age_days=' || DATE_DIFF('day', latest_snap, CURRENT_DATE) AS observed
FROM latest

UNION ALL

-- 2. UNIQUENESS: no duplicate (loan_id, snapshot_date) rows.
SELECT
    'UNIQUENESS' AS check_name,
    CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    '0 duplicate (loan_id, snapshot_date)' AS expected,
    COUNT(*)::VARCHAR || ' duplicates' AS observed
FROM (
    SELECT loan_id, snapshot_date, COUNT(*) AS n
    FROM fct_portfolio_snapshot
    GROUP BY 1, 2
    HAVING COUNT(*) > 1
)

UNION ALL

-- 3. REFERENTIAL_INTEGRITY: >= 95% of credit loan_ids match a customer.
WITH cov AS (
    SELECT
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE c.loan_id IS NOT NULL) AS matched
    FROM fct_portfolio_snapshot p
    LEFT JOIN dim_customer c USING (loan_id)
)
SELECT
    'REFERENTIAL_INTEGRITY' AS check_name,
    CASE WHEN matched::DOUBLE / NULLIF(total, 0) >= 0.95 THEN 'PASS' ELSE 'FAIL' END AS status,
    '>= 95% coverage' AS expected,
    ROUND(matched::DOUBLE / NULLIF(total, 0) * 100, 3)::VARCHAR || '% covered' AS observed
FROM cov

UNION ALL

-- 4. RANGE_CUSTOMER_AGE: ages between 18 and 100 when present.
SELECT
    'RANGE_CUSTOMER_AGE' AS check_name,
    CASE WHEN bad = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    'age in [18, 100]' AS expected,
    bad::VARCHAR || ' rows out of range' AS observed
FROM (
    SELECT COUNT(*) AS bad
    FROM fct_portfolio_snapshot
    WHERE customer_age_years IS NOT NULL
      AND (customer_age_years < 18 OR customer_age_years > 100)
)

UNION ALL

-- 5. RANGE_DAYS_PAST_DUE: 0..3650
SELECT
    'RANGE_DAYS_PAST_DUE' AS check_name,
    CASE WHEN bad = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    'days_past_due in [0, 3650]' AS expected,
    bad::VARCHAR || ' rows out of range' AS observed
FROM (
    SELECT COUNT(*) AS bad
    FROM fct_portfolio_snapshot
    WHERE days_past_due < 0 OR days_past_due > 3650
)

UNION ALL

-- 6. NULL_THRESHOLD_LOAN_ID: loan_id must be 0% null.
SELECT
    'NULL_LOAN_ID' AS check_name,
    CASE WHEN nulls = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    '0% null on loan_id' AS expected,
    nulls::VARCHAR || ' nulls' AS observed
FROM (
    SELECT COUNT(*) FILTER (WHERE loan_id IS NULL) AS nulls
    FROM fct_portfolio_snapshot
)

UNION ALL

-- 7. SCHEMA_DRIFT: required canonical columns present.
SELECT
    'SCHEMA_DRIFT' AS check_name,
    CASE WHEN missing = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
    'canonical columns present' AS expected,
    missing::VARCHAR || ' missing columns' AS observed
FROM (
    SELECT SUM(CASE WHEN col NOT IN (
        SELECT lower(column_name)
        FROM duckdb_columns()
        WHERE table_name = 'fct_portfolio_snapshot'
    ) THEN 1 ELSE 0 END) AS missing
    FROM (VALUES
        ('loan_id'), ('snapshot_date'), ('sale_date'),
        ('account_status_l1'), ('account_status_l2'),
        ('days_past_due'), ('arrears'), ('balance'), ('closing_balance')
    ) AS canonical(col)
);
