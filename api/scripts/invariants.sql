-- Nightly invariant check (SELECT only; run by scripts/check_invariants.py in a read-only transaction).
-- Each block starts with "-- name: <invariant>" and returns the violating rows: a name column and
-- ids only, never personal values. An invariant holds when its query returns no rows.
-- Mirrors tests/stateful/machine.py `check` (SPEC section 2 "Nightly invariant check").

-- name: orphan_exit
-- An exit whose holding row is gone in every state (purge deletes exits with their holding).
WITH h(asset_type, id) AS (
  SELECT 'fd', id FROM fixed_deposits UNION ALL SELECT 'rd', id FROM recurring_deposits
  UNION ALL SELECT 'stock', id FROM stocks UNION ALL SELECT 'bond', id FROM bonds
  UNION ALL SELECT 'mf', id FROM mutual_funds UNION ALL SELECT 'gold', id FROM gold_holdings
  UNION ALL SELECT 'other', id FROM other_holdings
)
SELECT 'orphan_exit' AS name, e.id AS exit_id
FROM holding_exits e
LEFT JOIN h ON h.asset_type = e.asset_type AND h.id = e.holding_id
WHERE h.id IS NULL;

-- name: orphan_funding
-- A funding whose holding row is gone in every state.
WITH h(asset_type, id) AS (
  SELECT 'fd', id FROM fixed_deposits UNION ALL SELECT 'rd', id FROM recurring_deposits
  UNION ALL SELECT 'stock', id FROM stocks UNION ALL SELECT 'bond', id FROM bonds
  UNION ALL SELECT 'mf', id FROM mutual_funds UNION ALL SELECT 'nps', id FROM nps_holdings
  UNION ALL SELECT 'gold', id FROM gold_holdings UNION ALL SELECT 'cash', id FROM cash_holdings
  UNION ALL SELECT 'pf', id FROM pf_holdings UNION ALL SELECT 'other', id FROM other_holdings
)
SELECT 'orphan_funding' AS name, f.id AS funding_id
FROM holding_fundings f
LEFT JOIN h ON h.asset_type = f.asset_type AND h.id = f.holding_id
WHERE h.id IS NULL;

-- name: funding_state_mismatch
-- SPEC 8c: a funding is active (refunded_at null) exactly while its holding is not soft-deleted.
-- This also holds for sold and settled holdings: those cannot be deleted (409), so they stay live
-- and their funding stays active.
WITH h(asset_type, id, deleted_at) AS (
  SELECT 'fd', id, deleted_at FROM fixed_deposits UNION ALL SELECT 'rd', id, deleted_at FROM recurring_deposits
  UNION ALL SELECT 'stock', id, deleted_at FROM stocks UNION ALL SELECT 'bond', id, deleted_at FROM bonds
  UNION ALL SELECT 'mf', id, deleted_at FROM mutual_funds UNION ALL SELECT 'nps', id, deleted_at FROM nps_holdings
  UNION ALL SELECT 'gold', id, deleted_at FROM gold_holdings UNION ALL SELECT 'cash', id, deleted_at FROM cash_holdings
  UNION ALL SELECT 'pf', id, deleted_at FROM pf_holdings UNION ALL SELECT 'other', id, deleted_at FROM other_holdings
)
SELECT 'funding_state_mismatch' AS name, f.id AS funding_id
FROM holding_fundings f
JOIN h ON h.asset_type = f.asset_type AND h.id = f.holding_id
WHERE (f.refunded_at IS NULL) <> (h.deleted_at IS NULL);

-- name: negative_cash
SELECT 'negative_cash' AS name, id AS cash_id FROM cash_holdings WHERE balance < 0;

-- name: duplicate_active_funding
-- At most one active funding per holding (also a partial unique index, uq_holding_fundings_active).
SELECT 'duplicate_active_funding' AS name, min(id) AS funding_id
FROM holding_fundings
WHERE refunded_at IS NULL
GROUP BY asset_type, holding_id
HAVING count(*) > 1;

-- name: duplicate_settlement
-- A deposit or bond is settled at most once.
SELECT 'duplicate_settlement' AS name, min(id) AS exit_id
FROM holding_exits
WHERE kind = 'maturity'
GROUP BY asset_type, holding_id
HAVING count(*) > 1;

-- name: mf_units_vs_transactions
-- A live, open fund that has transactions holds exactly the units they net to.
SELECT 'mf_units_vs_transactions' AS name, f.id AS fund_id
FROM mutual_funds f
JOIN (
  SELECT mutual_fund_id,
         sum(CASE WHEN kind = 'purchase' THEN units ELSE -units END) AS net
  FROM mf_transactions
  GROUP BY mutual_fund_id
) t ON t.mutual_fund_id = f.id
WHERE f.deleted_at IS NULL AND f.closed_on IS NULL AND round(f.units, 3) <> round(t.net, 3);

-- name: mf_transaction_missing_fund
SELECT 'mf_transaction_missing_fund' AS name, min(t.id) AS transaction_id
FROM mf_transactions t
LEFT JOIN mutual_funds f ON f.id = t.mutual_fund_id
WHERE f.id IS NULL
GROUP BY t.mutual_fund_id;

-- name: closed_without_sale
-- SPEC 8b: closed_on is only set by a full sale, which writes a sale exit. Settlements do not set it.
WITH c(asset_type, id) AS (
  SELECT 'stock', id FROM stocks WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'bond', id FROM bonds WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'mf', id FROM mutual_funds WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'gold', id FROM gold_holdings WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'other', id FROM other_holdings WHERE closed_on IS NOT NULL
)
SELECT 'closed_without_sale' AS name, c.asset_type, c.id AS holding_id
FROM c
WHERE NOT EXISTS (
  SELECT 1 FROM holding_exits e
  WHERE e.asset_type = c.asset_type AND e.holding_id = c.id AND e.kind = 'sale'
);

-- name: sale_cost_vs_invested
-- A full sale takes all of the invested amount that is left (it keeps invested_amount unchanged),
-- so the closing sale's cost equals the holding's invested amount (stocks: quantity x average
-- price, within a paisa of rounding). A partial sale reduces invested by its cost, so a partly sold
-- holding has no invested at the time of the sale left to compare: there the check is that
-- invested stays above zero (cost never exceeds what was invested), which the CHECK constraints
-- (invested >= 0) already enforce and the validated-constraints query below watches.
WITH last_sale AS (
  SELECT DISTINCT ON (asset_type, holding_id) asset_type, holding_id, id, cost
  FROM holding_exits
  WHERE kind = 'sale'
  ORDER BY asset_type, holding_id, id DESC
),
c(asset_type, id, invested) AS (
  SELECT 'bond', id, invested_amount FROM bonds WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'mf', id, invested_amount FROM mutual_funds WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'gold', id, invested_amount FROM gold_holdings WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'other', id, invested_amount FROM other_holdings WHERE closed_on IS NOT NULL
  UNION ALL SELECT 'stock', id, round(quantity * avg_buy_price, 2) FROM stocks WHERE closed_on IS NOT NULL
)
SELECT 'sale_cost_vs_invested' AS name, l.id AS exit_id
FROM c
JOIN last_sale l ON l.asset_type = c.asset_type AND l.holding_id = c.id
WHERE abs(l.cost - c.invested) > CASE WHEN c.asset_type = 'stock' THEN 0.01 ELSE 0 END;

-- name: deleted_holding_with_exit
-- API delete is 409 while a holding has an exit, undo deletes the exit row and purge removes exits
-- with the holding, so a soft-deleted holding never has an exit. (Only the seven exit types.)
WITH d(asset_type, id) AS (
  SELECT 'fd', id FROM fixed_deposits WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'rd', id FROM recurring_deposits WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'stock', id FROM stocks WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'bond', id FROM bonds WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'mf', id FROM mutual_funds WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'gold', id FROM gold_holdings WHERE deleted_at IS NOT NULL
  UNION ALL SELECT 'other', id FROM other_holdings WHERE deleted_at IS NOT NULL
)
SELECT 'deleted_holding_with_exit' AS name, e.id AS exit_id
FROM holding_exits e
JOIN d ON d.asset_type = e.asset_type AND d.id = e.holding_id;

-- name: closed_and_settled
-- Settle refuses a closed bond and a sale refuses a matured one, so a bond never has both closed_on
-- and a settlement. (Deposits have no closed_on.)
SELECT 'closed_and_settled' AS name, e.id AS exit_id
FROM holding_exits e
JOIN bonds b ON e.asset_type = 'bond' AND b.id = e.holding_id
WHERE e.kind = 'maturity' AND b.closed_on IS NOT NULL;

-- name: exit_after_full_sale
-- Once a full sale closes a holding every later sale or settlement is refused (and undo only takes
-- the latest exit), so no exit has a higher id than a full sale of the same holding. A full sale is
-- one whose prev_state says full; older rows without that key count when the holding is closed on
-- the sale's date (exits.py _was_full_sale). Part-sale then settle is legal, as nothing closes.
WITH h(asset_type, id, closed_on) AS (
  SELECT 'stock', id, closed_on FROM stocks UNION ALL SELECT 'bond', id, closed_on FROM bonds
  UNION ALL SELECT 'mf', id, closed_on FROM mutual_funds UNION ALL SELECT 'gold', id, closed_on FROM gold_holdings
  UNION ALL SELECT 'other', id, closed_on FROM other_holdings
),
full_sale AS (
  SELECT e.asset_type, e.holding_id, e.id
  FROM holding_exits e
  JOIN h ON h.asset_type = e.asset_type AND h.id = e.holding_id
  WHERE e.kind = 'sale'
    AND (e.prev_state->>'full' = 'true'
         OR (e.prev_state->>'full' IS NULL AND h.closed_on = e.exit_date))
)
SELECT 'exit_after_full_sale' AS name, e.id AS exit_id
FROM holding_exits e
JOIN full_sale f ON f.asset_type = e.asset_type AND f.holding_id = e.holding_id AND f.id < e.id;

-- name: exit_cash_mismatch
-- Exit rows agree with their destination: cash has a positive cash_added, none has neither
-- cash_added nor a cash account link. A null cash_holding_id alone is fine (the account was purged).
SELECT 'exit_cash_mismatch' AS name, id AS exit_id
FROM holding_exits
WHERE (destination = 'cash' AND (cash_added IS NULL OR cash_added <= 0))
   OR (destination = 'none' AND (cash_added IS NOT NULL OR cash_holding_id IS NOT NULL))
   OR (destination <> 'cash' AND cash_holding_id IS NOT NULL);

-- name: exit_kind_type_mismatch
-- Only fd, rd and bond are settled (kind maturity); only stock, bond, mf, gold and other are sold.
SELECT 'exit_kind_type_mismatch' AS name, id AS exit_id
FROM holding_exits
WHERE (kind = 'maturity' AND asset_type NOT IN ('fd', 'rd', 'bond'))
   OR (kind = 'sale' AND asset_type NOT IN ('stock', 'bond', 'mf', 'gold', 'other'));

-- name: invalid_constraint
-- Every constraint (the migration 0032 CHECKs among them) must stay validated, and the funding
-- unique index must stay valid.
SELECT 'invalid_constraint' AS name, c.oid::bigint AS constraint_oid
FROM pg_constraint c
WHERE NOT c.convalidated
UNION ALL
SELECT 'invalid_constraint', i.indexrelid::bigint
FROM pg_index i
WHERE NOT i.indisvalid;

-- name: missing_funding_unique_index
SELECT 'missing_funding_unique_index' AS name, 0 AS index_count
WHERE NOT EXISTS (
  SELECT 1 FROM pg_indexes WHERE indexname = 'uq_holding_fundings_active'
);
