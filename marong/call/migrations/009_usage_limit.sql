-- 009 Per-account usage limits: one function for a friend's call cost this month (CTX-006, SPEC-397, SPEC-399).
-- (docs/04-functional-spec/usage-limit.md 3.2; marong/migrations/021_usage_limit.sql.)
-- The sum is the one call_cost.personal_budget_blocked computes in main ad9f2f4, found by friend instead of caller.
-- The call server (blocking a call) and the app server (the share shown to the friend, the admin's dollars) call
-- this function, so both read the same number. The app server role still cannot read the call cost tables; it gets
-- the sum only. Months are UTC months: the caller passes the bounds (call_cost.bounds).
-- No table changes. Safe to run twice. Apply after 008 and marong migration 021, as the migration administrator.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

CREATE OR REPLACE FUNCTION call.friend_month_usd(p_friend bigint, p_start timestamptz, p_end timestamptz)
RETURNS numeric
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, call
AS $$
  WITH caller AS (SELECT id FROM call.callers WHERE friend_id = p_friend),
  totals AS (
    SELECT u.usd FROM call.live_usage u JOIN call.calls c ON c.id = u.call_id
    WHERE c.caller_id IN (SELECT id FROM caller) AND u.received_at >= p_start AND u.received_at < p_end
      AND (u.kind = 'estimate' OR (
        NOT EXISTS (SELECT 1 FROM call.segment_costs s WHERE s.segment_id = u.segment_ref AND s.estimated)
        AND NOT EXISTS (SELECT 1 FROM call.live_usage x WHERE x.segment_ref = u.segment_ref AND x.kind = 'estimate')))
    UNION ALL
    SELECT s.usd FROM call.segment_costs s JOIN call.calls c ON c.id = s.call_id
    WHERE c.caller_id IN (SELECT id FROM caller) AND s.opened_at >= p_start AND s.opened_at < p_end AND s.estimated
    UNION ALL
    SELECT (coalesce(r.input_tokens, 0)::bigint * p.text_in
            + (coalesce(r.output_tokens, 0)::bigint + coalesce(r.thoughts_tokens, 0)) * p.text_out) / 1000000
    FROM call.ai_runs r JOIN call.calls c ON c.id = r.call_id
    JOIN LATERAL (SELECT text_in, text_out FROM call.live_prices
                  WHERE model = r.model AND starts_at <= r.sent_at ORDER BY starts_at DESC, id DESC LIMIT 1) p ON true
    WHERE c.caller_id IN (SELECT id FROM caller) AND r.kind = 'organize' AND r.sent_at >= p_start AND r.sent_at < p_end
  )
  SELECT coalesce(sum(usd), 0) FROM totals
$$;
REVOKE ALL ON FUNCTION call.friend_month_usd(bigint, timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION call.friend_month_usd(bigint, timestamptz, timestamptz) TO marong, marong_call;

RESET ROLE;
COMMIT;
