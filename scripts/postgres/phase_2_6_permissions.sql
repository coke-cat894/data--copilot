\set ON_ERROR_STOP off

SELECT 1 AS select_check;
SELECT COUNT(*) AS metadata_check FROM information_schema.tables;
SELECT SUM(quantity * unit_price) AS aggregate_check
FROM commerce.order_items;
EXPLAIN (FORMAT JSON) SELECT * FROM commerce.orders WHERE order_id = 1;

INSERT INTO commerce.users VALUES (99999, 'Blocked', 'North', now());
UPDATE commerce.orders SET status = 'cancelled' WHERE order_id = 1;
DELETE FROM commerce.order_items WHERE order_item_id = 1;
CREATE TABLE commerce.blocked_create (id integer);
DROP TABLE commerce.orders;
ALTER TABLE commerce.orders ADD COLUMN blocked integer;
