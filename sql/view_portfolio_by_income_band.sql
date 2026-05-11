CREATE OR REPLACE VIEW v_portfolio_by_income_band AS
SELECT
    snapshot_date,
    COALESCE(avg_monthly_income_band, 'Unknown') AS income_band,
    COUNT(*)                                                          AS accounts,
    AVG((days_past_due > 0)::INT)                                     AS delinquency_rate,
    AVG((days_past_due >= 30)::INT)                                   AS par30_rate,
    AVG(is_write_off::INT)                                            AS write_off_rate,
    AVG(is_paid_off::INT)                                             AS paid_off_rate,
    AVG(balance)                                                      AS avg_balance
FROM fct_portfolio_snapshot
GROUP BY snapshot_date, income_band
ORDER BY snapshot_date, income_band;
