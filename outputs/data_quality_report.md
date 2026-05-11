# Data Quality Report

_Generated: 2026-05-11T08:15:10.904228Z_

## Summary

- **credit_2025-01-01** - 8,935 rows x 33 columns - source: `Credit Data - 2025-01-01.csv`
- **credit_2025-03-30** - 11,024 rows x 33 columns - source: `Credit Data - 2025-03-30.csv`
- **credit_2025-06-30** - 13,891 rows x 34 columns - source: `Credit Data - 2025-06-30.csv`
- **credit_2025-09-30** - 16,864 rows x 34 columns - source: `Credit Data - 2025-09-30.csv`
- **credit_2025-12-30** - 20,742 rows x 34 columns - source: `Credit Data - 2025-12-30.csv`
- **sales_sales_details** - 1,048,575 rows x 16 columns - source: `Sales and Customer Data.xlsx`
- **sales_gender** - 1,048,575 rows x 3 columns - source: `Sales and Customer Data.xlsx`
- **sales_dob** - 1,048,575 rows x 5 columns - source: `Sales and Customer Data.xlsx`
- **sales_income_level** - 1,048,575 rows x 6 columns - source: `Sales and Customer Data.xlsx`
- **nps** - 4,129 rows x 17 columns - source: `NPS Data.xlsx`

## Findings

| Severity | Dataset | Issue | Detail |
|----------|---------|-------|--------|
| HIGH | `sales_sales_details` | join_key_null | Loan Id is 98.026% NULL - join coverage will be poor |
| HIGH | `sales_gender` | join_key_null | Loan Id is 98.579% NULL - join coverage will be poor |
| HIGH | `sales_income_level` | join_key_null | Loan Id is 98.867% NULL - join coverage will be poor |
| MEDIUM | `credit_2025-01-01` | date_as_string | DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-01-01` | date_as_string | RETURN_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-01-01` | date_as_string | SALE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-01-01` | date_as_string | CREDIT_EXPIRY is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-01-01` | date_as_string | NEXT_INVOICE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-01-01` | date_as_string | MAX_PAYMENT_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | RETURN_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | SALE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | CREDIT_EXPIRY is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | NEXT_INVOICE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-03-30` | date_as_string | MAX_PAYMENT_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | RETURN_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | SALE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | CREDIT_EXPIRY is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | NEXT_INVOICE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-06-30` | date_as_string | MAX_PAYMENT_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | RETURN_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | SALE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | CREDIT_EXPIRY is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | NEXT_INVOICE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-09-30` | date_as_string | MAX_PAYMENT_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | RETURN_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | SALE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | CREDIT_EXPIRY is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | NEXT_INVOICE_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `credit_2025-12-30` | date_as_string | MAX_PAYMENT_DATE is stored as text - needs parse-and-cast |
| MEDIUM | `sales_dob` | date_as_string | date_of_birth is stored as text - needs parse-and-cast |

## Per-column null percentage (>= 1%)

### `credit_2025-01-01`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `PAYMENT_AMOUNT` | float64 | 93.621% | 193 |
| `ADJUSTMENT_AMOUNT` | float64 | 93.621% | 2 |
| `RETURN_DATE` | object | 88.965% | 380 |

### `credit_2025-03-30`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `PAYMENT_AMOUNT` | float64 | 94.131% | 216 |
| `ADJUSTMENT_AMOUNT` | float64 | 94.131% | 4 |
| `RETURN_DATE` | object | 89.251% | 428 |

### `credit_2025-06-30`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Unnamed: 28` | float64 | 100.0% | 0 |
| `PAYMENT_AMOUNT` | float64 | 93.514% | 253 |
| `ADJUSTMENT_AMOUNT` | float64 | 93.514% | 9 |
| `RETURN_DATE` | object | 89.907% | 479 |
| `MAX_PAYMENT_DATE` | object | 1.029% | 909 |

### `credit_2025-09-30`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Unnamed: 28` | float64 | 100.0% | 0 |
| `PAYMENT_AMOUNT` | float64 | 93.981% | 269 |
| `ADJUSTMENT_AMOUNT` | float64 | 93.981% | 5 |
| `RETURN_DATE` | object | 90.696% | 504 |
| `MAX_PAYMENT_DATE` | object | 1.222% | 909 |

### `credit_2025-12-30`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Unnamed: 28` | float64 | 100.0% | 0 |
| `PAYMENT_AMOUNT` | float64 | 99.855% | 24 |
| `ADJUSTMENT_AMOUNT` | float64 | 99.855% | 1 |
| `RETURN_DATE` | object | 91.592% | 1 |
| `MAX_PAYMENT_DATE` | object | 1.47% | 909 |

### `sales_sales_details`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `RETURN_DATE` | datetime64[ns] | 99.834% | 530 |
| `RETURN_POLICY_COMPLIANCE` | object | 99.834% | 2 |
| `SELLER_TYPE` | object | 98.495% | 5 |
| `SELLER` | object | 98.029% | 519 |
| `Loan Id` | object | 98.026% | 20691 |
| `CLIENT_MODEL` | object | 98.024% | 3 |
| `SALE_TYPE` | object | 98.022% | 3 |
| `CASH_PRICE` | float64 | 98.022% | 259 |
| `LOAN_PRICE` | float64 | 98.022% | 930 |
| `LOAN_TERM` | object | 98.022% | 3 |
| `PRODUCT_NAME` | object | 98.022% | 132 |
| `MODEL` | object | 98.022% | 82 |
| `SALE_ID` | object | 98.021% | 20747 |
| `SALE_DATE` | datetime64[ns] | 98.021% | 939 |
| `RETURNED` | float64 | 98.021% | 2 |
| `BUSINESS_MODEL` | object | 98.021% | 7 |

### `sales_gender`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Loan Id` | object | 98.579% | 10497 |
| `Citizenship` | object | 95.252% | 3 |
| `Gender` | object | 95.252% | 5 |

### `sales_dob`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Loan Id ` | object | 98.707% | 11217 |
| `date_of_birth` | object | 94.572% | 17087 |
| `_id` | object | 94.552% | 57130 |
| `provider` | object | 94.552% | 3 |
| `createdAt UTC` | object | 94.552% | 57130 |

### `sales_income_level`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `Loan Id` | object | 98.867% | 10609 |
| `Duration` | float64 | 97.822% | 23 |
| `Received` | float64 | 97.822% | 21191 |
| `Persons Received From Total` | float64 | 97.822% | 20993 |
| `Banks Received` | float64 | 97.822% | 16632 |
| `Paybills Received Others` | float64 | 97.822% | 12560 |

### `nps`

| Column | Dtype | Nulls % | Distinct |
|--------|-------|---------|----------|
| `What is one thing we could do to improve your experience with us?` | object | 72.536% | 1068 |
| `What is the main reason for your score?` | object | 71.349% | 1060 |
| `Any other Feedback?` | object | 57.544% | 1163 |
| `(If Yes) – Please describe the challenge you faced and how we can improve your experience.` | object | 52.531% | 1339 |
| `Have you ever had your phone lock despite making a payment on time?` | object | 50.836% | 2 |
| `Which communication channel do you prefer when contacting MoPhones for inquiries or support?` | object | 50.666% | 5 |
| `Have you used the MoPhones app (MoApp) to manage your account or make payments?` | object | 50.109% | 3 |
| `Have you experienced any battery-related issues with your MoPhones device?` | object | 49.6% | 2 |
| `Have you ever had difficulty getting assistance from ABC Phones customer support when needed?` | object | 43.037% | 3 |
| `Have you ever experienced a delay in your payment reflecting in your ABC account?` | object | 42.625% | 2 |
| `Are you happy with the service and support provided by ABC Phones?` | object | 36.837% | 2 |
| `Are you happy with the quality and performance of your device?` | object | 36.377% | 2 |
| `Using a scale from 0 (not likely) to 10 (very likely), how likely are you to recommend ABC Phones to friends or family?` | float64 | 3.488% | 11 |


## Data Quality Check Results

_Generated: 2026-05-11T08:18:33.683215Z_

| Check | Severity | Status | Expected | Observed |
|-------|----------|--------|----------|----------|
| FRESHNESS | HIGH | **FAIL** | latest snapshot <= 100 days old | latest=2025-12-30, age_days=132 |
| UNIQUENESS | CRITICAL | **PASS** | 0 duplicate (loan_id, snapshot_date) rows | 0 duplicate rows |
| REFERENTIAL_INTEGRITY | HIGH | **PASS** | coverage >= 95% | coverage=99.909% |
| RANGE_CUSTOMER_AGE | MEDIUM | **PASS** | age in [18, 100] | 0 out-of-range / 27770 non-null |
| RANGE_DAYS_PAST_DUE | HIGH | **PASS** | days_past_due in [0, 3650] | 0 out-of-range / 71456 |
| NULL_LOAN_ID | HIGH | **PASS** | <= 0.0% null | 0.000% null |
| NULL_DATE | HIGH | **PASS** | <= 0.0% null | 0.000% null |
| NULL_SALE_DATE | HIGH | **PASS** | <= 0.0% null | 0.000% null |
| NULL_ACCOUNT_STATUS_L1 | MEDIUM | **PASS** | <= 50.0% null | 0.000% null |
| NULL_ACCOUNT_STATUS_L2 | MEDIUM | **PASS** | <= 50.0% null | 0.000% null |
| SCHEMA_DRIFT | CRITICAL | **PASS** | columns present: ['loan_id', 'date', 'sale_date', 'account_status_l1', 'account_status_l2', 'days_past_due', 'arrears', 'balance', 'closing_balance'] | all present |

### Failure detail

- **FRESHNESS**: Latest snapshot is 2025-12-30 (132 days old).