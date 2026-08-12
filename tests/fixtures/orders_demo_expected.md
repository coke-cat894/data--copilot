# Orders Demo Ground Truth

This file is for manual acceptance only. Data Copilot must not read it or place
it in Agent context.

## Definitions

- Revenue means `sum(amount)` for rows where `status = completed`.
- Completed order count means the number of rows where `status = completed`.
- Region average means `avg(amount)` for rows where `status = completed`.
- Exact duplicate count means duplicate rows beyond the first occurrence.

## Dataset shape

- Row count: 48 data rows
- Column count: 6
- Columns: `order_id`, `user_id`, `region`, `amount`, `status`, `created_at`
- Date range: 2026-01-03 through 2026-04-30
- Rows per month: 12 in each month

## Monthly completed revenue and order count

| Month | Revenue | Completed orders | Average completed amount |
|---|---:|---:|---:|
| 2026-01 | 1050 | 10 | 105 |
| 2026-02 | 1050 | 10 | 105 |
| 2026-03 | 520 | 5 | 104 |
| 2026-04 | 1050 | 10 | 105 |

## Completed order amount by region

| Region | Completed revenue | Completed orders | Average amount |
|---|---:|---:|---:|
| North | 1100 | 11 | 100 |
| South | 630 | 7 | 90 |
| East | 1100 | 10 | 110 |
| West | 840 | 7 | 120 |

- Highest-average region: West, with an average completed order amount of 120.
- There are no ties for the highest average.

## Expected data-quality observations

- Exact duplicate rows beyond the first: 1.
  - `ORD-035,U035,South,90,cancelled,2026-03-26` appears twice.
- Null observations: 1.
  - `user_id` is null for `ORD-034`.
- Negative numeric observations: 1.
  - `amount = -20` for cancelled order `ORD-023`.
- No dates are later than 2026-04-30.
- No extra constant column was added.

## March decline explanation

March completed revenue is 520, down 530 (about 50.5%) from February's 1050.
The observable explanation is that completed order count fell from 10 to 5,
while average completed order amount changed only from 105 to 104. April
returns to 10 completed orders and revenue recovers to 1050.
