# 마롱이 관리 페이지 다시 만들기: DB 표

상태: 초안(2026-11-23 새벽 KST, Claude 마롱이 봇). 이 PR은 문서만이라 마이그레이션 파일을 만들지 않았어요. 아래 3절의 함수를 TASK-490에서 GPT가 `marong/call/migrations/011_admin_month.sql`로 만들고, 서버 반영 때 적용해요.
입력: [기능 명세](../04-functional-spec/admin.md) SPEC-450\~457(3.4 통화 월 예산 함수), [도메인](../01-domain/admin.md), 통합 앱 표 [unified.md](unified.md)의 TBL-164(`marong.invites`)·167(`marong.friend_profiles`), 사람별 사용 한도 표 [usage-limit.md](usage-limit.md)의 `call.friend_month_usd`, 앱 업데이트 기능 변경(PR #101)의 TBL-182(`app_update_events`, [`docs/05-erd/app-update.md`](app-update.md)에 PR #101이 더함).
API 계약: [`api/admin.openapi.yaml`](../../api/admin.openapi.yaml)의 API-280·281.

## 1. 바뀌는 것

새 표, 새 칸, 새 TBL 번호는 없어요. 통화 스키마에 읽기 함수 하나만 더해요. 지우거나 이름을 바꾸는 것이 없어서 지금 `main`(`7b0c6e1`)의 코드가 그대로 돌아요.

| 곳 | 더하는 것 | 뜻 | 명세 |
| --- | --- | --- | --- |
| 함수 `call.month_budget(p_start, p_end)` | `RETURNS TABLE(spent_usd numeric, budget_usd numeric)`, `STABLE SECURITY DEFINER`, `search_path = pg_catalog, call` | 이번 UTC 달의 통화 비용 합(통화 서버의 `call_cost.MONTH` 쿼리의 `total`과 같은 식)과 월 예산(`call.settings`의 `monthly_budget_usd`, 없으면 150). 앱 서버(`marong` 역할)가 표를 읽지 않고 이 두 숫자만 받아요 | SPEC-457 |

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
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;
CREATE OR REPLACE FUNCTION call.month_budget(p_start timestamptz, p_end timestamptz)
RETURNS TABLE(spent_usd numeric, budget_usd numeric)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, call
AS $$
  -- 본문: call_cost.MONTH의 WITH limits(lo, hi) … SELECT live+estimated+search_usd+organize 를
  -- %s 자리 대신 p_start, p_end로 옮긴 것(식은 한 글자도 바꾸지 않음),
  -- 그리고 coalesce((SELECT (value #>> '{}')::numeric FROM call.settings WHERE key = 'monthly_budget_usd'), 150)
$$;
REVOKE ALL ON FUNCTION call.month_budget(timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION call.month_budget(timestamptz, timestamptz) TO marong;
RESET ROLE;
COMMIT;
```

- 함수 본문은 일부러 옮겨 적지 않았어요. GPT가 만들 때 `call_cost.MONTH`를 그대로 옮겨야 두 식이 같아지기 때문이에요. 같은지는 TC-631이 같은 합성 자료로 `CallCost.report()`의 `total`과 비교해 지켜요.
- `marong_call`(통화 서버 역할)에는 권한을 주지 않아요. 통화 서버는 지금처럼 자기 쿼리를 써요.
- 번호 011은 통화 마이그레이션의 다음 번호예요(`main`과 열린 PR #100·#101에서 가장 큰 번호가 010, 2026-11-23 확인).

## 4. 검사

- 이 PR에서 DB에 돌린 것은 없어요. 함수는 TASK-490의 끝 조건(TC-631·632)으로 버리는 Postgres(`pgserver`, 합성 행)에서 확인해요.
- 새 표가 없어서 ERD 그림은 바뀌지 않아요([erd.md](erd.md) 그대로).
