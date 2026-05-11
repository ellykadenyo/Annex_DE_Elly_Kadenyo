CREATE OR REPLACE VIEW v_portfolio_by_age_band AS
SELECT
    snapshot_date,
    COALESCE(age_band, 'Unknown') AS age_band,
    COUNT(*)                                                          AS accounts,
    AVG((days_past_due > 0)::INT)                                     AS delinquency_rate,
    AVG((days_past_due >= 30)::INT)                                   AS par30_rate,
    AVG(is_write_off::INT)                                            AS write_off_rate,
    AVG(is_paid_off::INT)                                             AS paid_off_rate,
    AVG(balance)                                                      AS avg_balance,
    AVG(CASE WHEN arrears > 0 THEN arrears END)                       AS avg_arrears
FROM fct_portfolio_snapshot
GROUP BY snapshot_date, age_band
ORDER BY snapshot_date, age_band;
