# 마롱이 관리 페이지 다시 만들기: DB 표

상태: 초안(2026-11-23 새벽 KST, Claude 마롱이 봇). 이 PR은 문서만이라 마이그레이션 파일을 만들지 않았어요. 아래 3절의 함수를 TASK-490에서 GPT가 `marong/call/migrations/011_admin_month.sql`로 만들고, 서버 반영 때 적용해요.
입력: [기능 명세](../04-functional-spec/admin.md) SPEC-450\~457(3.4 통화 월 예산 함수), [도메인](../01-domain/admin.md), 통합 앱 표 [unified.md](unified.md)의 TBL-164(`marong.invites`)·167(`marong.friend_profiles`), 사람별 사용 한도 표 [usage-limit.md](usage-limit.md)의 `call.friend_month_usd`, 앱 업데이트 기능 변경(PR #101)의 TBL-182(`app_update_events`, [`docs/05-erd/app-update.md`](app-update.md)에 PR #101이 더함).
API 계약: [`api/admin.openapi.yaml`](../../api/admin.openapi.yaml)의 API-280·281.

## 1. 바뀌는 것

새 표, 새 칸, 새 TBL 번호는 없어요. 통화 스키마에 읽기 함수 하나를 더하고, 009의 함수 하나는 `search_path`만 바꿔요. 지우거나 이름을 바꾸는 것이 없어서 지금 `main`(`15889ff`)의 코드가 그대로 돌아요.

| 곳 | 더하는 것 | 뜻 | 명세 |
| --- | --- | --- | --- |
| 함수 `call.month_budget(p_start, p_end)` | `RETURNS TABLE(spent_usd numeric, budget_usd numeric)`, `STABLE SECURITY DEFINER`, `SET search_path = pg_catalog, pg_temp`, 본문 `BEGIN ATOMIC` | 이번 UTC 달의 통화 비용 합(통화 서버의 `call_cost.MONTH` 쿼리의 `total`과 같은 식)과 월 예산(`call.settings`의 `monthly_budget_usd`, 없으면 150). 앱 서버(`marong` 역할)가 표를 읽지 않고 이 두 숫자만 받아요 | SPEC-457 |
| 함수 `call.friend_month_usd`(통화 마이그레이션 009, 바뀜) | `search_path`만 `pg_catalog, call` → `pg_catalog, pg_temp`(011의 `ALTER FUNCTION`. 본문과 권한은 그대로) | `SECURITY DEFINER` 함수가 이름을 찾는 곳을 새 함수와 같게 굳혀요(3절). 값은 바뀌지 않아요 | SPEC-457 |

## 2. 관리 페이지가 읽는 표(바뀌지 않음)

| 표 | 누가 읽나 | 어떻게 | 화면 |
| --- | --- | --- | --- |
| TBL-164 `marong.invites` | API-240(목록), API-235(만들기), API-281(거두기 제안, `revoked_at`만 UPDATE) | 지금 그대로. `revoked_at` 칸과 열린 링크 색인 `invites_open_idx`(`used_at IS NULL AND revoked_at IS NULL`)는 이미 있어요(마이그레이션 020) | SCR-202 |
| TBL-167 `marong.friend_profiles`, `marong.friends`, `marong.app_sessions`, `marong.usage_daily` | API-236, 243, 237, 241, 그리고 API-280의 회원 수·오늘 사용 합 | 지금 그대로. API-280의 오늘 사용 합은 API-236과 같은 조인에서 합만 내요 | SCR-169, 200, 201 |
| `marong.diary_ai_runs`, `marong.scene_pictures`, `marong.character_jobs` | API-266과 API-280의 그림 칸 | 지금 API-266의 쿼리 그대로(같은 서버 함수) | SCR-169, 204 |
| `call.*`(통화 비용 표들) | `call.friend_month_usd`(API-236), 새 `call.month_budget`(API-280) | 함수로만. 앱 서버 역할은 표를 직접 읽지 못해요(지금 그대로) | SCR-169, 201, 204 |
| TBL-182 `marong.app_update_events`, 릴리스 폴더의 `history.json`·`release.json` | API-267(PR #101)만 | 관리 페이지는 API-267의 응답만 읽어요. 이 part는 이 표와 파일을 직접 읽지 않고 형식도 정하지 않아요. API-280의 앱 칸도 API-267을 만드는 같은 서버 함수의 결과에서 세요 | SCR-169, 201, 203 |

## 3. 함수 정의(TASK-490이 만들 마이그레이션의 내용)

```sql
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
```

- 본문은 `call_cost.MONTH`를 옮긴 것이고 다른 곳은 셋뿐이에요. ① `limits`는 `SELECT p_start AS lo, p_end AS hi`예요. 인자가 이미 `timestamptz`라서 `MONTH`의 `%s::timestamptz` 캐스트를 뺐어요. ② 마지막 `SELECT`는 `total`의 식과 예산 두 값만 내요. ③ 본문이 `BEGIN ATOMIC`이에요. 합하는 식은 그대로예요. 구현 때 그때의 `MONTH`와 다시 맞추고, 같은지는 TC-631이 같은 합성 자료로 `MonthlyCost.report(at, fresh=True)`의 `total`과 비교해 지켜요.
- `search_path` 끝에 `pg_temp`를 적는 이유: 적지 않으면 Postgres가 표·타입 이름을 부르는 세션의 임시 스키마(`pg_temp`)에서 먼저 찾아요[사실]. 그러면 `marong` 역할이 임시 스키마에 같은 이름의 표나 도메인(CHECK 안에 자기 함수)을 만들어, 그 코드를 함수 주인(`marong_owner`) 권한으로 돌릴 수 있어요. 함수·연산자는 `pg_temp`에서 찾지 않아요[사실]. 마롱 마이그레이션 019(`019_persona.sql`)가 이미 `pg_catalog, pg_temp`를 써요[사실].
- 남는 캐스트는 키워드 타입(`::bigint`, `::numeric`)뿐이에요. 키워드 타입은 문법이 `pg_catalog`의 타입으로 바로 읽어서 `search_path`를 거치지 않아요[사실]. 키워드가 아닌 타입 이름(예: `timestamptz`, `jsonb`)이 필요해지면 `pg_catalog.`을 붙여요.
- 009의 `call.friend_month_usd`도 지금 `search_path = pg_catalog, call`이에요. 본문에 키워드가 아닌 타입 이름이 없어 지금은 뚫리지 않지만[사실], 같은 모양으로 맞춰요. 이미 적용된 009 파일은 고치지 않고 011의 `ALTER FUNCTION`으로 바꿔요. 본문이 모든 표에 `call.`을 붙여서 `call`을 빼도 값이 같아요(TC-632).
- `marong_call`(통화 서버 역할)에는 권한을 주지 않아요. 통화 서버는 지금처럼 자기 쿼리를 써요.
- 번호 011은 통화 마이그레이션의 다음 번호예요(PR #101을 합친 `main` `15889ff`과 열린 PR #100에서 가장 큰 번호가 010, 2026-11-23 확인).

## 4. 검사

- 운영 DB에는 아무것도 돌리지 않았어요.
- 2026-11-23에 3절의 SQL을 버리는 Postgres 16.2(`pgserver`, `tests/pg.py`로 통화 마이그레이션 010까지 적용)에 두 번 적용했고 오류가 없었어요. 두 함수의 `proconfig`는 `search_path=pg_catalog, pg_temp`, `call.month_budget`의 본문은 `BEGIN ATOMIC`, `marong_call`과 `PUBLIC`은 실행 권한이 없고, `marong`은 `call.live_usage`를 읽지 못했어요. 예산 행이 없으면 150, 있으면 그 값이었어요.
- 같은 DB에서 `marong` 역할 세션에 `pg_temp` 가로채기(부르면 오류를 내는 함수, 그 함수를 CHECK에 쓰는 도메인 `pg_temp.timestamptz`, 임시 표 `settings`·`live_usage`)를 만들었어요. 대조군인 옛 모양(`search_path = pg_catalog, call`과 `p_start::timestamptz`)은 가로채기 함수가 `marong_owner`로 돌았고, 3절의 두 함수는 값이 같고 가로채기 함수가 돌지 않았어요.
- 통화 서버 합과 같은지는 빈 통화 표에서만 봤어요(둘 다 0). 행이 있는 비교(TC-631)는 TASK-490에서 해요.
- 새 표가 없어서 ERD 그림은 바뀌지 않아요([erd.md](erd.md) 그대로).
