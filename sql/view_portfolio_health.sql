-- v_portfolio_health: snapshot-level portfolio KPIs.
--   delinquency_rate   = share of accounts with days_past_due > 0
--   par30_rate         = share of accounts with days_past_due >= 30
--   write_off_rate     = share of accounts flagged as Write Off (cumulative loss proxy)
--   paid_off_rate      = share of accounts fully repaid (retention/maturation signal)
--   collection_rate    = total_paid / total_due_today (cash recovery ratio)
--   avg_arrears        = mean arrears per delinquent account
CREATE OR REPLACE VIEW v_portfolio_health AS
SELECT
    snapshot_date,
    COUNT(*)                                                          AS accounts,
    AVG((days_past_due > 0)::INT)                                     AS delinquency_rate,
    AVG((days_past_due >= 30)::INT)                                   AS par30_rate,
    AVG((days_past_due >= 60)::INT)                                   AS par60_rate,
    AVG(is_write_off::INT)                                            AS write_off_rate,
    AVG(is_paid_off::INT)                                             AS paid_off_rate,
    AVG(is_returned::INT)                                             AS return_rate,
    CASE WHEN SUM(total_due_today) > 0
         THEN SUM(total_paid)::DOUBLE / SUM(total_due_today)
         ELSE NULL END                                                AS collection_rate,
    AVG(CASE WHEN arrears > 0 THEN arrears END)                       AS avg_arrears,
    AVG(balance)                                                      AS avg_balance,
    SUM(balance)                                                      AS portfolio_balance
FROM fct_portfolio_snapshot
GROUP BY snapshot_date
ORDER BY snapshot_date;
