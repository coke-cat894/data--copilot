# Order Status Policy

## Completed Orders

An order becomes completed after fulfillment confirmation. Completed status is
the eligibility gate used by the synthetic revenue policy.

## Cancelled Orders

Cancelled orders represent purchases stopped before fulfillment. They do not
contribute to completed revenue, even if line items were previously created.
