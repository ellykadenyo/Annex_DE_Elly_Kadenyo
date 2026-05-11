# Portfolio Insights

## 3A. Portfolio Health

**Headline KPIs (first vs last snapshot):**

- Delinquency: 42.2% -> 45.3%
- PAR 30: 35.4% -> 38.0%
- Write Off: 13.6% -> 18.0%
- Paid Off: 14.1% -> 25.8%
- Collection rate: 75.3% -> 72.4%

**Most-stressed customer segments (mean delinquency across snapshots):**

- Age band:
  - `18-25` -> 37.8%
  - `26-35` -> 34.5%
  - `36-45` -> 30.4%
- Income band:
  - `Below 5,000` -> 40.9%
  - `5,000-9,999` -> 40.4%
  - `10,000-19,999` -> 37.8%

**Latest snapshot risk mix:**

- Critical: 7,239 accounts | balance KES 341,159,259
- High: 655 accounts | balance KES 27,030,646
- Medium: 646 accounts | balance KES 28,767,033
- Low: 12,202 accounts | balance KES 271,590,820

## 3B. Credit Outcomes x Customer Experience

- Mean NPS for *current* respondents: **6.89**
- Mean NPS for respondents at PAR 30+: **5.15**
- Spread = **1.75** NPS points.

### NPS by Days-Past-Due bucket

| DPD bucket | Respondents | Avg NPS | Promoter % | Detractor % |
|------------|-------------|---------|------------|-------------|
| 0 (current) | 2,221 | 6.89 | 43.0% | 35.9% |
| 1-7 | 93 | 6.22 | 36.6% | 44.1% |
| 8-30 | 92 | 6.49 | 45.7% | 42.4% |
| 31-60 | 60 | 5.82 | 36.7% | 45.0% |
| 61-90 | 34 | 5.29 | 41.2% | 52.9% |
| 90+ | 247 | 4.33 | 25.5% | 63.6% |
| no_match | 1,238 | 7.22 | 46.5% | 31.4% |

**Recommendation.** Customers experiencing payment friction report lower NPS. Decoupling collections messaging from product satisfaction surveys, and routing PAR 7-30 accounts to a low-friction self-service repayment flow (MoApp) before involving a human collector, should lift CX and recover cash sooner.

## 3C. Data Gaps & Improvements

**Missing.** No employment-type column, no location/region, no per-transaction ledger (only balances), no device-level cost or financing margin.

**Inconsistent.** Date formats vary across files (`mm/dd/yyyy` in credit CSVs, ISO+TZ in DOB), schema drift between credit snapshots (later snapshots add an `Unnamed: 28` column), and Excel sheets pad to ~1M rows with blanks.

**Ambiguous.** `CUSTOMER_AGE` in the credit CSV is actually days-since-sale, not the customer's age; the `ACCOUNT_STATUS_L1` taxonomy mixes lifecycle stages with delinquency buckets (e.g. `First Month Default without inventory 08-14`).

**Proposed improvements.**
1. Move sales / DOB / income / NPS to a transactional system that emits JSON events to Kafka (or polled hourly via Airbyte) instead of Excel sheets - eliminates blank-row padding and gives an append-only audit trail.
2. Add an authoritative `customer_id` foreign key (separate from `loan_id`) so multi-loan customers can be analysed at the person level.
3. Normalise the account-status taxonomy to two orthogonal columns: `lifecycle_status` and `dpd_bucket`. This is what analysts already approximate via L1+L2; encoding it once at source will remove the need for downstream string parsing.