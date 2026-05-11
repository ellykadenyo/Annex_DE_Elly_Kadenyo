CREATE OR REPLACE VIEW v_portfolio_by_risk AS
SELECT
    snapshot_date,
    risk_category,
    COUNT(*)                          AS accounts,
    SUM(balance)                      AS balance,
    AVG(days_past_due)                AS avg_dpd,
    AVG(CASE WHEN arrears > 0 THEN arrears END) AS avg_arrears
FROM fct_portfolio_snapshot
GROUP BY snapshot_date, risk_category
ORDER BY snapshot_date,
         CASE risk_category
            WHEN 'Critical' THEN 1
            WHEN 'High'     THEN 2
            WHEN 'Medium'   THEN 3
            WHEN 'Low'      THEN 4
            ELSE 5 END;
