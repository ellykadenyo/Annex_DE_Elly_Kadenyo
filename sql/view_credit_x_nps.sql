-- v_credit_x_nps: joins each NPS response to the latest portfolio snapshot at
-- or before the survey submission date. This avoids leaking future events
-- into the customer experience reading.
CREATE OR REPLACE VIEW v_credit_x_nps AS
WITH latest_snapshot AS (
    SELECT
        n.submission_id,
        n.loan_id,
        n.nps_score,
        n.nps_bucket,
        n.submitted_at,
        f.snapshot_date,
        f.days_past_due,
        f.arrears,
        f.balance,
        f.risk_category,
        f.age_band,
        f.avg_monthly_income_band,
        f.account_status_l2,
        ROW_NUMBER() OVER (
            PARTITION BY n.submission_id
            ORDER BY f.snapshot_date DESC
        ) AS rn
    FROM fct_nps n
    LEFT JOIN fct_portfolio_snapshot f
      ON f.loan_id = n.loan_id
     AND f.snapshot_date <= COALESCE(n.submitted_at, CURRENT_DATE)
)
SELECT *
FROM latest_snapshot
WHERE rn = 1;
