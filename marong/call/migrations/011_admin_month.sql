-- 011 Admin overview: this UTC month's call cost and the monthly budget, as two numbers (SPEC-457).
-- Same sum as tools/vertex_live/call_cost.py MONTH (total = live + estimated + search_usd + organize).
-- The app server role still cannot read the call cost tables. No table changes. Safe to run twice.
-- SECURITY DEFINER: search_path ends with pg_temp, so a caller's temporary tables, types and domains are never
-- found before pg_catalog; every table is written call.<name>; casts use keyword types only; the body is
-- BEGIN ATOMIC (Postgres 14+), so its names are bound when this file runs, not when a caller runs it.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;
CREATE OR REPLACE FUNCTION call.month_budget(p_start timestamptz, p_end timestamptz)
RETURNS TABLE(spent_usd numeric, budget_usd numeric)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
BEGIN ATOMIC
  WITH limits AS (SELECT p_start AS lo, p_end AS hi),
  turns AS (
      SELECT COALESCE(sum(usage.usd) FILTER (WHERE NOT EXISTS (
          SELECT 1 FROM call.segment_costs s WHERE s.segment_id=usage.segment_ref AND s.estimated
      ) AND NOT EXISTS (
          SELECT 1 FROM call.live_usage saved WHERE saved.segment_ref=usage.segment_ref AND saved.kind='estimate'
      )),0) AS live,
      COALESCE(sum(usage.searches),0) AS search_count
      FROM call.live_usage usage, limits WHERE usage.kind='turn' AND usage.received_at>=lo AND usage.received_at<hi
  ), estimates AS (
      SELECT COALESCE(sum(usd),0) AS estimated, count(*) AS estimated_segments FROM (
          SELECT s.usd FROM call.segment_costs s, limits WHERE s.opened_at>=lo AND s.opened_at<hi AND s.estimated
          UNION ALL
          SELECT u.usd FROM call.live_usage u, limits WHERE u.received_at>=lo AND u.received_at<hi AND u.kind='estimate'
      ) all_estimates
  ), searches AS (
      SELECT CASE WHEN p.id IS NULL THEN 0 ELSE
        greatest(0,t.search_count-p.search_free_per_month)*p.search_per_1000/1000 END AS search_usd
      FROM turns t CROSS JOIN limits LEFT JOIN LATERAL (
          SELECT id,search_free_per_month,search_per_1000 FROM call.live_prices
          WHERE starts_at<hi AND search_per_1000>0 ORDER BY starts_at DESC,id DESC LIMIT 1
      ) p ON true
  ), organizer AS (
      SELECT COALESCE(sum((COALESCE(r.input_tokens,0)::bigint*p.text_in+
        (COALESCE(r.output_tokens,0)::bigint+COALESCE(r.thoughts_tokens,0))*p.text_out)/1000000),0) AS organize,
        count(*) FILTER (WHERE p.id IS NULL) AS organize_unpriced
      FROM call.ai_runs r CROSS JOIN limits LEFT JOIN LATERAL (
        SELECT id,text_in,text_out FROM call.live_prices
        WHERE model=r.model AND starts_at<=r.sent_at ORDER BY starts_at DESC LIMIT 1
      ) p ON true
      WHERE r.kind='organize' AND r.sent_at>=lo AND r.sent_at<hi
  )
  SELECT live+estimated+search_usd+organize,
         COALESCE((SELECT (value #>> '{}')::numeric FROM call.settings WHERE key='monthly_budget_usd'),150)
  FROM turns, estimates, searches, organizer;
END;
REVOKE ALL ON FUNCTION call.month_budget(timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION call.month_budget(timestamptz, timestamptz) TO marong;
-- 009's call.friend_month_usd gets the same search_path. 009 is applied and is not edited; its body already
-- writes call.<name> for every table and casts only to keyword types, so it returns the same values.
ALTER FUNCTION call.friend_month_usd(bigint, timestamptz, timestamptz) SET search_path = pg_catalog, pg_temp;
RESET ROLE;
COMMIT;
