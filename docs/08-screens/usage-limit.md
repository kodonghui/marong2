# 사람별 사용 한도와 내 사용량: 화면 상태(08)

상태: 초안(2026-11-21 KST, Claude). 아직 만들지 않았어요. 새 화면은 없고, 있는 화면 넷의 상태가 바뀌거나 늘어요.
입력: [사이트맵](../07-sitemap/sitemap.yaml)의 SCR-165·169·107·001(FL-179를 더함), [기능 명세](../04-functional-spec/usage-limit.md) SPEC-397\~399와 3.3\~3.5절, API 계약 [`api/unified.openapi.yaml`](../../api/unified.openapi.yaml) 0.2.0-draft의 API-216·234·236·240·243, 도메인 TERM-199(계정 한도)·TERM-200(기본 한도).
바탕: 이 문서는 [통합 앱 화면](unified.md)의 SCR-165·169 표에서 바뀌는 줄만 적어요. 적지 않은 상태는 그 문서 그대로예요. 토큰과 부품은 [`design/README.md`](../../design/README.md)를 따르고 새 토큰은 더하지 않아요(09단계 토큰은 얼려 둠, D67).
와이어프레임: [마롱이 내 사용량 와이어프레임](https://claude.ai/artifact/W1E3o6x6THzQ1oTbYxtcey)(원본 [`design/usage-limit-wireframe.html`](../../design/usage-limit-wireframe.html)). 칩을 눌러 상태를 바꿔 볼 수 있어요. 숫자와 이름은 지어낸 값이에요.

| 번호 | 화면 | 바뀌는 곳 | 절 |
| --- | --- | --- | --- |
| SCR-165 | 내 마롱이 | '오늘 쓴 양' 그룹 → '내 사용량' 카드(하루 한도·티켓·이번 달 통화) | [1](#1-scr-165-내-마롱이의-내-사용량) |
| SCR-169 | 관리자(D136 1-6: 날짜 이름표는 SCR-202, 기본 한도 줄은 SCR-200, 계정 한도와 '한도 바꾸기'는 SCR-201로 옮김) | 초대 링크 날짜 이름표, 기본 한도 줄, 사람 줄의 계정 한도와 '한도 바꾸기' | [2](#2-scr-169-관리자) |
| SCR-107 | 글 대화 | #daily-limit 띠의 링크 이름 '내 사용량 보기' | [3](#3-하루-한도-안내scr-107001) |
| SCR-001 | 통화 홈 | #daily-limit에 '내 사용량 보기' 링크 | [3](#3-하루-한도-안내scr-107001) |

## 1. SCR-165 내 마롱이의 '내 사용량'

Purpose: 로그인한 친구가 자기의 오늘 사용량, 하루 한도, 티켓, 이번 달 통화가 한도의 몇 %인지를 봐요. 다른 사람의 값은 없어요. (FL-179, FL-177, REQ-488·489)

| Data | Source |
| --- | --- |
| 오늘 글 답 수·통화 초·그림 수·사용 단위, 유효 하루 한도(`limit`), 티켓 | API-234(`chatTurns`, `callSeconds`, `images`, `units`, `limit`, `tickets`) |
| 이번 달 통화(`callMonth.limited`, `percent`, `resetsAt`). 달러는 없음 | API-234(`callMonth`) |
| 화면을 처음 열 때의 같은 값 | API-216(`usageToday`, API-234와 같은 모양) |

| Action | Result | Failure |
| --- | --- | --- |
| '다시 해 볼게'(카드 오류일 때) | API-234 다시 → #usage… | 다시 #usage-error |

카드는 위에서부터 줄 넷이에요(SPEC-399 3.3). 막대는 한도가 있을 때만 그려요.

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-165#usage | 카드 이름 '내 사용량'. 첫 줄 '오늘 · 글 답 12번 · 통화 8분 · 그림 1장'. 그 아래 하루 한도·티켓·이번 달 통화 줄이 아래 상태대로 보임. 통화 초는 분으로 내림, 0분이면 '통화 0분' | API-234#200, API-216#200 |
| SCR-165#usage-unlimited | 줄 '하루 한도 · 무제한'(막대 없음) | API-234#200(`limit=null`) |
| SCR-165#usage-limit | 막대(`units`/`limit`, 100%에서 멈춤)와 '오늘 320 / 1000' | API-234#200(`limit` 있음, `units` < `limit`) |
| SCR-165#usage-over | 막대가 가득 차고, 티켓이 0이면 '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져', 티켓이 있으면 '오늘 양을 넘어서 티켓으로 이어 가는 중이야' | API-234#200(`units` ≥ `limit`) |
| SCR-165#tickets | 줄 '티켓 3장'. 0장이면 줄이 없음 | API-234#200(`tickets` > 0) |
| SCR-165#call-month-unlimited | 줄 '이번 달 통화 · 무제한'(막대 없음) | API-234#200(`callMonth.limited=false`) |
| SCR-165#call-month | 막대(`percent`, 100에서 멈춤)와 '40% 썼어 · 12월 1일 오전 9시에 다시 채워져'. 날짜는 `resetsAt`을 한국 시각 짧은 모양으로 | API-234#200(`callMonth.percent` < 100) |
| SCR-165#call-month-over | 막대가 가득 차고 '이번 달 통화를 다 썼어. 12월 1일 오전 9시에 다시 채워져'. 글 대화는 그대로 쓸 수 있음 | API-234#200(`callMonth.percent` ≥ 100) |
| SCR-165#call-month-unknown | 그 줄만 '이번 달 통화 양은 지금 못 불러왔어'. 다른 줄은 그대로 | API-234#200(`callMonth.limited=true`, `percent=null`) |
| SCR-165#usage-error | 카드만 '지금은 못 불러왔어'와 '다시 해 볼게'. 다른 그룹은 그대로 씀 | API-234#default, API-234#503(`db_unavailable`) |

[통합 앱 화면](unified.md#scr-165-내-마롱이)의 SCR-165#normal에서 그룹 이름 '오늘 쓴 양'은 '내 사용량'이 되고, 그 문서의 #usage·#usage-limit·#usage-over·#usage-error는 이 표가 대신해요. 비어 있음: 오늘 쓴 것이 없으면 '오늘 · 글 답 0번 · 통화 0분 · 그림 0장'이에요. 오래된 데이터: 화면이 다시 보일 때 API-234를 다시 읽어요. 통화를 마치고 돌아오면 이번 달 %가 바뀌어 있을 수 있어요.

## 2. SCR-169 관리자

화면 자리 바뀜(D136 1-6, 2026-11-23): 관리 페이지가 여섯 화면으로 나뉘어 이 절의 표시는 초대 링크(SCR-202, 날짜 이름표), 회원(SCR-200, 기본 한도 줄과 사람 줄의 '한도 · …'), 회원 한 사람(SCR-201, 계정 한도와 '한도 바꾸기', 이번 달 통화 비용), 비용(SCR-204, 사람마다 통화 비용)으로 옮겼어요. 이름표와 문구는 한 글자도 바꾸지 않았어요. 상태마다 옮긴 곳을 적었어요 → [admin.md](admin.md) 6절.

Purpose: 동희님이 초대 링크의 만든 때·쓴 때·만료를 구분해 보고, 사람마다 계정 한도를 무제한·기본·직접 가운데 하나로 정하고, 이번 달 통화 비용을 봐요. (FL-179, FL-169, FL-177, REQ-487·431, 동희님 관찰 2026-11-21 15:46 KST)

| Data | Source |
| --- | --- |
| 초대 링크의 만든 때·만료·쓴 때·거둔 때 | API-240(`createdAt`, `expiresAt`, `usedAt`, `revokedAt`) |
| 기본 한도 둘(서버 설정값, 화면에서 바꾸지 않음) | API-236(`defaults`) |
| 사람마다 계정 한도, 유효 한도, 이번 달 통화 비용(달러) | API-236(`members[].limits`, `effective`, `callMonthUsd`) |
| 바꾼 뒤의 계정 한도와 유효 한도 | API-243 |

| Action | Result | Failure |
| --- | --- | --- |
| 한도 바꾸기(사람 줄) | 칸이 열림 → #limits-edit. 지금 값이 골라져 있음 | 없음 |
| '무제한'·'기본 한도'·'직접 정하기' 칩 | 하나가 골라짐. '직접 정하기'면 숫자 칸 둘이 열림 → #limits-custom | 없음 |
| 저장 | API-243 `{mode, dailyUnits?, callMonthlyUsd?}` → 200 → #limits-saved | 400 → #limits-invalid, 404 → #limits-missing |
| 그만두기 | 칸이 닫히고 줄은 그대로 | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-169#normal(바뀜. D136 1-6 → 초대 링크 줄 SCR-202#normal, 기본 한도 줄과 사람 줄 SCR-200#normal) | 초대 링크 줄은 세 줄: '종류 · 메모', 상태('열림'·'씀(쓴 사람)'·'기간 지남'·'거둠'), 날짜 줄(아래 #invite-…). '가입한 사람' 그룹 위에 '기본 한도 · 하루 1000 · 통화 월 $3.00'(비어 있으면 '없음'). 사람 줄에 한 줄 더 '한도 · …'와 '이번 달 통화 $1.23', 버튼 '한도 바꾸기'. '마지막 사용'은 짧은 날짜 모양 | API-240#200, API-236#200 |
| SCR-169#invite-open(D136 1-6 → SCR-202#invite-open) | 날짜 줄 '만든 때 11월 21일 오후 2:59 · 만료 11월 28일 오후 2:59(7일 남음)'. 하루가 안 남았으면 '(오늘 끝나요)' | API-240#200(`state=open`) |
| SCR-169#invite-used(D136 1-6 → SCR-202#invite-used) | 날짜 줄 '만든 때 11월 21일 오후 2:59 · 쓴 때 11월 21일 오후 3:01' | API-240#200(`state=used`) |
| SCR-169#invite-expired(D136 1-6 → SCR-202#invite-expired) | 날짜 줄 '만든 때 11월 12일 오후 7:16 · 만료됨 11월 19일 오후 7:16'. 줄 글자가 흐림 | API-240#200(`state=expired`) |
| SCR-169#invite-revoked(D136 1-6 → SCR-202#invite-revoked) | 날짜 줄 '만든 때 11월 12일 오후 7:16 · 거둔 때 11월 13일 오전 9:00'. 줄 글자가 흐림 | API-240#200(`state=revoked`) |
| SCR-169#created(바뀜. D136 1-6 → SCR-202#created) | 끝나는 때 자리에 '만료 11월 28일 오후 2:59(7일 뒤)' | API-235#201 |
| SCR-169#limit-unlimited(D136 1-6 → SCR-200#normal·SCR-201#normal의 '한도 · …' 줄) | 사람 줄 '한도 · 무제한' | API-236#200(`limits.mode=unlimited`) |
| SCR-169#limit-default(D136 1-6 → SCR-200#normal·SCR-201#normal의 '한도 · …' 줄) | 사람 줄 '한도 · 기본(하루 1000 · 통화 월 $3.00)'. 기본 한도가 비어 있으면 '없음' | API-236#200(`limits.mode=default`) |
| SCR-169#limit-custom(D136 1-6 → SCR-200#normal·SCR-201#normal의 '한도 · …' 줄) | 사람 줄 '한도 · 직접(하루 200 · 통화 월 $5.00)'. 비운 쪽은 '기본 따름' | API-236#200(`limits.mode=custom`) |
| SCR-169#call-month-unknown(D136 1-6 → SCR-201#call-month-unknown, SCR-204#person-unknown) | 모든 사람 줄의 통화 비용이 '이번 달 통화 —' | API-236#200(`callMonthUsd=null`) |
| SCR-169#limits-edit(D136 1-6 → SCR-201#limits-edit) | 줄 아래 칸: 칩 셋과 '저장'·'그만두기'. 지금 `mode`의 칩이 골라져 있음 | |
| SCR-169#limits-custom(D136 1-6 → SCR-201#limits-custom) | 숫자 칸 둘 '하루 사용 단위'(1\~100000), '통화 월 달러'(0.01\~1000)와 안내 '비운 칸은 기본 한도를 따라요'. 둘 다 비었으면 '저장'이 꺼짐 | |
| SCR-169#limits-saving(D136 1-6 → SCR-201#limits-saving) | 칩·칸·버튼 꺼짐 | |
| SCR-169#limits-saved(D136 1-6 → SCR-201#limits-saved) | 칸이 닫히고 그 줄의 '한도 · …'가 응답의 `limits`로 바뀌고 띠 '한도를 바꿨어요'. 그 친구의 다음 요청부터 적용돼요 | API-243#200 |
| SCR-169#limits-invalid(D136 1-6 → SCR-201#limits-invalid) | 칸 아래 '숫자를 확인해 주세요(하루 1\~100000, 통화 월 0.01\~1000)', 쓴 값 남김 | API-243#400(`invalid_input`) |
| SCR-169#limits-missing(D136 1-6 → SCR-201#missing) | '그 사람을 찾을 수 없어요. 목록을 다시 불러올게요' → API-236 다시 | API-243#404(`not_found`) |
| SCR-169#error(늘어남. D136 1-6 → 공통#error) | 공통 규칙('잠깐 문제가 생겼어요. 다시 해 볼까요?') | API-243#403(`cross_site`), API-243#503(`db_unavailable`), API-243#default |

권한: Access를 지나지 못하면 이 화면이 열리지 않아요(API-243도 403 `not_allowed`). 대화 글, 토큰은 이 화면에 없어요. 달러 값은 이 화면에만 있어요. 오래된 데이터: 한도를 바꾼 뒤에는 응답 값으로 그 줄만 바꾸고, 화면이 다시 보일 때 목록 전체를 다시 읽어요.

## 3. 하루 한도 안내(SCR-107·001)

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-107#daily-limit(바뀜) | 띠의 링크 이름이 '내 마롱이에서 보기'에서 '내 사용량 보기'(SCR-165의 '내 사용량' 카드로 스크롤)로 바뀌어요. '한도 설정이 없으면'은 '그 사람의 유효 하루 한도가 없으면'으로 읽어요. 무제한 계정에는 이 상태가 나오지 않아요 | API-103#429(`daily_limit`) |
| SCR-001#daily-limit(바뀜) | 문구 아래 링크 '내 사용량 보기'(SCR-165). 통화 버튼은 그대로 막힘 | API-124#200(`blockedReason=daily_limit`), API-107#101(메시지 `daily_limit`) |

통화 월 한도로 막힌 통화는 지금처럼 `budget_exhausted` 상태(SCR-001의 예산 문구)예요. 전체 예산과 사람별 한도를 화면에서 나누지 않아요(이유가 달라도 친구가 할 일은 같아서).

## 4. 날짜 모양

- 관리자 화면과 '내 사용량'의 날짜는 한국 시각 짧은 모양이에요: 올해면 '11월 21일 오후 2:59', 다른 해면 '2025년 11월 21일 오후 2:59', 시각이 필요 없는 다시 채워지는 날은 '12월 1일 오전 9시'(분이 0이면 분을 빼요).
- 이 모양은 공통 `date` 함수(`unified.js`, '2026. 11. 28. 오후 2:59')를 바꾸지 않고 따로 둬요. 다른 화면의 날짜는 그대로예요.
- '(7일 남음)'·'(7일 뒤)'는 지금 시각에서 만료까지의 날 수(올림)예요. 하루가 안 남았으면 '(오늘 끝나요)'예요.

## 5. 와이어프레임 목록

와이어프레임은 아래를 눌러 바꿔 보게 그렸어요(전화 폭 390px, 관리자는 넓은 폭도).

1. SCR-165 '내 사용량' 카드: 무제한 계정(#usage-unlimited·#call-month-unlimited), 한도 있음(#usage-limit·#tickets·#call-month), 넘음(#usage-over·#call-month-over), 통화 합 못 읽음(#call-month-unknown), 카드 오류(#usage-error).
2. SCR-169 초대 링크 줄 넷(#invite-open·used·expired·revoked)과 지금 화면(이름표 없는 날짜) 비교. 2026-11-23부터 이 줄은 SCR-202에 있어요(D136 1-6).
3. SCR-169 사람 줄과 '한도 바꾸기' 칸(#limit-…, #limits-edit·custom·invalid·saved). 2026-11-23부터 사람 줄은 SCR-200·201, '한도 바꾸기'는 SCR-201에 있어요(D136 1-6).
4. SCR-107·001 #daily-limit의 '내 사용량 보기' 링크.
