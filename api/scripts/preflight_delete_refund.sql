-- Preflight for the delete-refund fix. READ-ONLY: SELECT statements only, safe on prod.
-- Finds holding_fundings rows marked refunded (refunded_at set) whose cash account was already
-- soft-deleted at that time (deleted_at <= refunded_at). The old bug set refunded_at on such a
-- delete without crediting the account. Run in psql or the Neon SQL editor.

-- 1. How many rows (should be 0 once any are reviewed).
SELECT count(*) AS affected_fundings
FROM holding_fundings f
JOIN cash_holdings c ON c.id = f.cash_holding_id
WHERE f.refunded_at IS NOT NULL
  AND c.deleted_at IS NOT NULL
  AND c.deleted_at <= f.refunded_at;

-- 2. The rows themselves.
SELECT f.user_id, f.asset_type, f.holding_id, f.cash_holding_id, f.amount, f.refunded_at
FROM holding_fundings f
JOIN cash_holdings c ON c.id = f.cash_holding_id
WHERE f.refunded_at IS NOT NULL
  AND c.deleted_at IS NOT NULL
  AND c.deleted_at <= f.refunded_at
ORDER BY f.refunded_at, f.id;
