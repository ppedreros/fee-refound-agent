-- The latest check of Ana's case, step by step: what ran, on which model, how long it took,
-- the tokens and the cost, and what the models were sent (masked).
--   Get-Content docs/demo/trace.sql | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
\pset footer off

\echo
\echo '== The run'
SELECT status, outcome, would_auto_approve, total_latency_ms, tokens_in, tokens_out,
       tokens_cached, cost_usd, provider_mode->>'jev' AS mode
FROM agent_runs WHERE case_id = 5012 ORDER BY started_at DESC LIMIT 1;

\echo '== Each step'
SELECT node, kind, coalesce(model, '') AS model, prompt_version, latency_ms,
       tokens_in, tokens_out, tokens_cached, cost_usd
FROM agent_steps
WHERE run_id = (SELECT id FROM agent_runs WHERE case_id = 5012 ORDER BY started_at DESC LIMIT 1)
ORDER BY id;

\echo '== What Jev was asked (triage) and what Sol was given (draft): masked, no names'
SELECT node, jsonb_pretty(input_masked) AS input
FROM agent_steps
WHERE run_id = (SELECT id FROM agent_runs WHERE case_id = 5012 ORDER BY started_at DESC LIMIT 1)
  AND node IN ('triage', 'draft')
ORDER BY id;
