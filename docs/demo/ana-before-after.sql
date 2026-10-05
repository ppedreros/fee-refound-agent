-- Ana's money and case, as the database holds them. Run it before and after the refund:
--   Get-Content docs/demo/ana-before-after.sql | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
\pset footer off

\echo
\echo '== Everyday Checking (sub-account 1302)'
SELECT name, balance, available FROM sub_accounts WHERE id = 1302;

\echo '== Its transactions since Sep 14, newest first'
SELECT date, posting_ref, description, amount, balance_after
FROM transactions
WHERE sub_account_id = 1302 AND date >= '2026-09-14'
ORDER BY date DESC, posting_ref DESC;

\echo '== Refunds the app posted'
SELECT fee_txn_id, refund_txn_id, amount, created_at FROM refunds;

\echo '== The conversation and the case'
SELECT c.status AS conversation, k.status AS "case", k.updated_at
FROM conversations c LEFT JOIN cases k ON k.conversation_id = c.id
WHERE c.id = 5012;

\echo '== The decision (who, when, what, why)'
SELECT staff_id, action, created_at, coalesce(reason, '(approved as recommended)') AS reason
FROM decisions WHERE case_id = 5012;

\echo '== The audit trail (append-only)'
SELECT at, actor, action, details FROM audit_events WHERE case_id = 5012 ORDER BY id;
