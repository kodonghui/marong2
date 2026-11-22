# 관리 페이지 다시 만들기: 화면 상태(08)

상태: 초안(2026-11-23 새벽 KST, Claude 마롱이 봇). 아직 만들지 않았어요. 새 화면 다섯(SCR-200\~204)과 바뀌는 화면 둘(SCR-169 개요, SCR-186 탭 줄)이에요.
입력: [사이트맵](../07-sitemap/sitemap.yaml)의 SCR-169·186·200\~204, [기능 명세](../04-functional-spec/admin.md) SPEC-450\~457과 3.1\~3.6절, API 계약 [`api/admin.openapi.yaml`](../../api/admin.openapi.yaml)(API-280·281), [`api/unified.openapi.yaml`](../../api/unified.openapi.yaml)(API-235\~243), [`api/pet-app.openapi.yaml`](../../api/pet-app.openapi.yaml)(API-263\~266), 앱 업데이트 PR #101의 `api/app-update.openapi.yaml`(API-267), 지금 화면 정의 [unified.md](unified.md)의 SCR-169, [usage-limit.md](usage-limit.md)의 SCR-169, [pet-app.md](pet-app.md)의 SCR-186.
바탕: 지금 관리자 화면의 문구는 한 글자도 바꾸지 않고 옮겨요(아래 6절의 대응표). 새 문구는 [새 제안]이에요. 토큰과 부품은 [`design/README.md`](../../design/README.md)와 지금 `unified.css`·`chat.css`를 따르고 새 토큰은 더하지 않아요(D67, 09 단계).
와이어프레임: [`design/admin-wireframe.html`](../../design/admin-wireframe.html)(회색, 시스템 글꼴, 상태마다 한 칸, 폭 360px와 430px 나란히). 숫자와 이름은 지어낸 값이에요.

| 번호 | 화면 | 경로 | 절 |
| --- | --- | --- | --- |
| 공통 | 탭 줄, 막힘, 오류, 폭 | | [1](#1-공통) |
| SCR-169 | 개요(바뀜) | `/chat/admin/` | [2](#2-scr-169-개요) |
| SCR-200 | 회원 | `/chat/admin/members` | [3](#3-scr-200-회원) |
| SCR-201 | 회원 한 사람 | `/chat/admin/members/:friendId` | [4](#4-scr-201-회원-한-사람) |
| SCR-202 | 초대 링크 | `/chat/admin/invites` | [5](#5-scr-202-초대-링크) |
| SCR-203 | 앱 버전 | `/chat/admin/app` | [7](#7-scr-203-앱-버전) |
| SCR-204 | 비용 | `/chat/admin/costs` | [8](#8-scr-204-비용) |
| SCR-186 | 아이템(탭 줄만 바뀜) | `/chat/admin/items` | [9](#9-scr-186-아이템) |
| 대응표 | 지금 SCR-169 상태 → 새 상태 | | [6](#6-지금-scr-169-상태가-가는-곳) |

## 1. 공통

- 머리: 제목 '마롱이 관리'와 그 아래 탭 줄(개요 · 회원 · 초대 링크 · 앱 버전 · 비용 · 아이템). 탭 줄은 화면 위에 붙어 있고(스크롤해도 보임), 지금 탭은 굵은 글자와 밑줄, `aria-current="page"`. 탭은 높이 44px 이상의 링크예요.
- 폭: 한 줄 기둥(본문 폭 최대 720px, 가운데). 좌우 여백 16px. 360px에서 탭 여섯이 한 줄에 들어가지 않으면 탭 줄 안에서만 옆으로 밀리고 오른쪽 끝을 흐리게 해요. 페이지는 가로로 넘치지 않아요(REQ-581). 430px도 같은 한 줄 기둥이에요.
- 테마: 지금 관리자 화면처럼 `data-theme="night"`예요.
- 시각: 한국 시각의 짧은 모양(`shortDate`, 예: '11월 24일 오후 2:03')이에요. 통화 비용의 달은 'UTC'를 붙여 적어요.
- 돈: '$121.40'처럼 달러 기호와 소수 둘째 자리예요(지금 관리자 화면과 같음).

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| 공통#forbidden | 탭 줄 없이 '관리자만 볼 수 있어요' 한 줄. Access를 지나지 못하면 Cloudflare 로그인 화면이 먼저 떠서 이 상태는 Access는 지났지만 관리자가 아닐 때예요 | 화면 경로 403, API-280·281·235\~243·263\~267의 403(`not_allowed`) |
| 공통#error | 그 그룹 자리에 '잠깐 문제가 생겼어요. 다시 해 볼까요?'(지금 문구)와 '다시 해 볼게요' 단추. 추적 id는 작은 글씨 | 각 API의 500·503·`cross_site`·네트워크 실패 |
| 공통#stale | 화면이 다시 보이면(`visibilitychange`) 그 화면의 목록을 다시 읽어요. 읽는 동안 숫자는 그대로 두고 맨 위에 얇은 막대 | (다시 읽기) |
| 공통#not-found | '없는 화면이에요'와 '개요로' 링크 | 3.1에 없는 하위 경로의 404 |

## 2. SCR-169 개요

Purpose: 동희님이 관리 페이지를 열면 손볼 일을 먼저 보고, 숫자 다섯으로 지금 상태를 한눈에 봐요. (FL-200, REQ-572·573, TERM-240·241)

| Data | Source |
| --- | --- |
| 주의 항목(종류, 단계, 숫자, 갈 화면) | API-280 `attention` |
| 회원 수, 잇지 않은 친구 수 | API-280 `members` |
| 오늘 사용 합(단위, 글 답, 통화 분, 그림) | API-280 `usageToday` |
| 이번 달 통화 합·월 예산·비율·상태(UTC 달) | API-280 `callMonth` |
| 이번 달 그림 비용 합과 예산 비율(한국 시각 달) | API-280 `images` |
| 최신 앱 버전, 멈춤, 폰 수, 뒤처진 폰 수 | API-280 `app` |

| Action | Result | Failure |
| --- | --- | --- |
| 주의 항목 한 줄 누름 | 그 줄의 `target` 화면으로 감 | 없음 |
| 숫자 카드 누름 | 회원 → SCR-200, 오늘 → SCR-200, 통화·그림 → SCR-204, 앱 → SCR-203 | 없음 |
| 다시 해 볼게요 | API-280 다시 | 공통#error |

주의 항목의 문구[새 제안]:

| `kind` | `warn` | `danger` |
| --- | --- | --- |
| `call_budget` | '통화 월 예산 {value}% 썼어요' | '통화 월 예산을 넘었어요({value}%) · 새 통화가 막혀요' |
| `image_budget` | '그림 예산 {value}% 썼어요' | '그림 예산을 다 썼어요 · 새 캐릭터 만들기가 막혀요' |
| `app_paused` | '앱 업데이트를 멈춰 둔 상태예요' | |
| `app_behind` | '새 버전을 아직 받지 못한 폰 {value}대' | '설치가 멈춘 폰 {value}대 · 확인 창 기다림이나 실패' |
| `invite_expiring` | '24시간 안에 끝나는 초대 링크 {value}개' | |
| `unlinked_friend` | '아직 잇지 않은 기존 친구 {value}명' | |

`warn` 줄은 노란 점, `danger` 줄은 빨간 점과 굵은 글자예요(지금 `danger` 부품). 모르는 `kind`가 오면 그 줄을 그리지 않아요(API가 먼저 늘어나도 화면이 깨지지 않음).

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-169#loading | 주의 항목 자리 회색 한 줄, 카드 다섯 자리 회색(받은 뒤에도 자리가 움직이지 않음) | |
| SCR-169#attention | 맨 위 그룹 '손볼 일'에 줄 n개(위 문구), 그 아래 카드 다섯 | API-280#200(`attention` 1개 이상) |
| SCR-169#calm | '손볼 일' 그룹에 '지금 손볼 일 없어요' 한 줄, 그 아래 카드 다섯 | API-280#200(`attention` 빈 목록) |
| SCR-169#cards | 카드 다섯: '회원 3명 · 잇지 않은 친구 1명', '오늘 단위 420 · 글 41 · 통화 21분 · 그림 2', '통화 11월(UTC) $121.40 / $150.00 · 80%'와 막대, '그림 11월 $21.10 · 예산 85%', '앱 최신 0.3.3 · 폰 2대 중 1대 뒤처짐'(멈춤이면 '업데이트 멈춤 중') | API-280#200 |
| SCR-169#card-unknown | `null`인 칸의 카드만 '지금 못 불러왔어요'. 나머지 카드와 주의 항목은 그대로 | API-280#200(`callMonth`·`images`·`app`·`usageToday` 가운데 `null`) |
| SCR-169#budget-off | 통화 카드 '통화 11월(UTC) $30.00 · 예산 꺼짐', 막대 없음 | API-280#200(`callMonth.state=off`) |
| SCR-169#no-release | 앱 카드 '아직 올린 버전이 없어요' | API-280#200(`app.latest=null`) |
| SCR-169#error | 공통#error(화면 전체) | API-280#503(`db_unavailable`), API-280#500 |
| SCR-169#forbidden | 공통#forbidden | API-280#403(`not_allowed`) |

## 3. SCR-200 회원

Purpose: 가입한 사람을 한 줄씩 보고 한 사람 화면으로 들어가요. 잇지 않은 기존 친구에게 잇기 링크를 만들러 가요. (FL-200, FL-177, REQ-574)

| Data | Source |
| --- | --- |
| 기본 한도 둘 | API-236 `defaults` |
| 가입한 사람(이름, 마롱이 이름, 계정 한도, 오늘 단위, 티켓, 마지막 사용) | API-236 `members` |
| 잇지 않은 기존 친구(이름) | API-236 `unlinked` |

| Action | Result | Failure |
| --- | --- | --- |
| 사람 줄 누름 | SCR-201 | 없음 |
| 잇기 링크 만들기(잇지 않은 친구 줄) | SCR-202 `?kind=link&friend={friendId}` | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-200#loading | 기본 한도 줄과 사람 줄 세 개 자리 회색 | |
| SCR-200#normal | 맨 위 '기본 한도 · 하루 1000 · 통화 월 $3.00'(비어 있으면 '없음', usage-limit 문구). 사람 줄: 첫 줄 '이름 · 마롱이 이름', 둘째 줄 '한도 · …'(usage-limit SCR-169#limit-* 문구), 셋째 줄 '오늘 320단위 · 티켓 3장 · 마지막 11월 24일 오후 2:03'. 오른쪽 끝 '›' | API-236#200 |
| SCR-200#unlinked | 아래 그룹 '아직 잇지 않은 기존 친구'에 이름과 '잇기 링크 만들기' | API-236#200(`unlinked` 1명 이상) |
| SCR-200#empty | '아직 가입한 사람이 없어요'(지금 #members-empty 문구) | API-236#200(`members` 빈 목록) |
| SCR-200#error | 공통#error | API-236#500·503 |
| SCR-200#forbidden | 공통#forbidden | API-236#403 |

## 4. SCR-201 회원 한 사람

Purpose: 한 사람의 한도·사용량·로그인·폰을 한 화면에서 보고, 한도 바꾸기·티켓 넣기·로그인 끊기를 해요. (FL-200, FL-179, FL-177, FL-171, REQ-575·582·487·482)

| Data | Source |
| --- | --- |
| 이름, 마롱이 이름, 계정 한도, 유효 한도, 오늘 사용량, 티켓, 로그인 수, 마지막 사용, 이번 달 통화 비용 | API-236(그 `friendId`의 줄) |
| 바꾼 뒤의 계정 한도 | API-243 |
| 티켓 잔액 | API-237 |
| 이 사람의 폰(버전, 뒤처짐, 마지막 보고) | API-267 `devices`에서 `friendId`가 같은 줄(명세 3.5) |

| Action | Result | Failure |
| --- | --- | --- |
| 한도 바꾸기 | usage-limit SCR-169#limits-edit와 같은 칸이 이 화면 '한도' 그룹 안에서 열림 → 저장 → API-243 → #limits-saved | 400 → #limits-invalid, 404 → #missing |
| 티켓 넣기(1\~1000) | 숫자 칸과 '넣기' → API-237 → #ticket-added | 400 → #ticket-invalid |
| 로그인 끊기 | 확인 줄(#revoke-confirm) → '끊기' → API-241 → #revoked. 응답 전에는 단추가 꺼짐 | 공통#error |
| 다시 로그인 링크 만들기 | SCR-202 `?kind=relogin&friend={friendId}` | 없음 |
| 앱 버전에서 보기 | SCR-203 `#friend={friendId}` | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-201#loading | 머리(이름) 자리와 그룹 넷(한도, 오늘, 로그인, 폰) 회색 | |
| SCR-201#normal | 머리 '이름 · 마롱이 이름'과 '‹ 회원'. 그룹 '한도': '한도 · …', '유효 · 하루 1000 · 통화 월 $3.00', '이번 달 통화 $1.23'과 '한도 바꾸기'. 그룹 '오늘': '320단위 · 글 12 · 통화 5분 · 그림 1'과 '티켓 3장', '티켓 넣기'. 그룹 '로그인': '로그인 2개 · 마지막 11월 24일 오후 2:03', '다시 로그인 링크 만들기', 빨간 '로그인 끊기'. 그룹 '이 사람의 폰' | API-236#200 |
| SCR-201#missing | '그 사람을 찾을 수 없어요'와 '회원 목록으로'(지금 #member-missing 문구의 앞 문장) | API-236#200(그 `friendId` 없음), API-243#404, API-237#404 |
| SCR-201#call-month-unknown | '이번 달 통화 —'(usage-limit 문구) | API-236#200(`callMonthUsd=null`) |
| SCR-201#limits-edit | usage-limit SCR-169#limits-edit 그대로(칩 셋, '저장'·'그만두기') | |
| SCR-201#limits-custom | usage-limit SCR-169#limits-custom 그대로 | |
| SCR-201#limits-saving | usage-limit SCR-169#limits-saving 그대로 | |
| SCR-201#limits-saved | 칸이 닫히고 '한도 · …'와 '유효 · …'가 응답 값으로 바뀌고 띠 '한도를 바꿨어요' | API-243#200 |
| SCR-201#limits-invalid | usage-limit SCR-169#limits-invalid 그대로 | API-243#400(`invalid_input`) |
| SCR-201#ticket | 숫자 칸(1\~1000)과 '넣기'(지금 #ticket) | |
| SCR-201#ticket-invalid | 칸 아래 '1부터 1000까지 넣어 주세요' | API-237#400(`invalid_input`) |
| SCR-201#ticket-added | '티켓 n장'이 새 잔액이 되고 띠 '티켓을 넣었어요' | API-237#200 |
| SCR-201#revoke-confirm | 확인 줄 '이 사람의 모든 기기 로그인을 끊어요. 다시 들어오려면 다시 로그인 링크가 필요해요'와 '끊기'·'그만두기'(지금 문구) | |
| SCR-201#revoked | '로그인 0개'와 띠 '로그인을 끊었어요' | API-241#204 |
| SCR-201#phones | 폰마다 한 줄 '폰 1 · 0.3.2 · 뒤처짐 · 마지막 보고 11월 24일 오후 2:03'과 '앱 버전에서 보기' | API-267#200(그 `friendId`의 폰 있음) |
| SCR-201#phones-none | '90일 안에 보고한 폰이 없어요' | API-267#200(그 `friendId`의 폰 없음) |
| SCR-201#phones-cap | 폰 줄 20개 아래 회색 글 '최근 보고한 20대만 보여요' | API-267#200(그 `friendId`의 폰이 20줄, PR #101 SPEC-438의 상한) |
| SCR-201#phones-unknown | 폰 그룹만 '지금 못 불러왔어요' | API-267#403·500·503, 네트워크 실패 |
| SCR-201#error | 공통#error | API-236#500·503, API-243#403(`cross_site`)·503, API-237#403(`cross_site`)·503, API-241#403(`cross_site`)·500 |

## 5. SCR-202 초대 링크

Purpose: 새 초대 링크를 만들고, 링크가 열렸는지·쓰였는지·끝났는지 이름표로 봐요. 열린 링크를 거둘 수 있어요(제안). (FL-169·170·171, FL-200, REQ-576·583·430·431)

| Data | Source |
| --- | --- |
| 초대 링크 목록(종류, 메모, 상태, 만든 때·만료·쓴 때·거둔 때, 쓴 사람). 토큰과 주소는 없음 | API-240 |
| `link`·`relogin`에서 고를 사람 | API-236(`members`, `unlinked`) |
| 새 링크의 주소와 만료(한 번만) | API-235 |
| 거둔 링크 | API-281(제안) |

| Action | Result | Failure |
| --- | --- | --- |
| 새 링크 만들기 | 지금 SCR-169의 만들기 칸 그대로(#creating) → API-235 → #created | 400 → #invite-invalid, 404 → #member-missing |
| 주소 복사 | '복사했어요'(지금 그대로) | 복사 실패 → 주소 글자를 골라 둠 |
| 칩 '열림'·'전체' | 그 상태만 보임 | 없음 |
| 거두기(제안, 열린 줄) | 확인 줄 → '거두기' → API-281 → #revoked-now | 409 → #invite-closed, 404 → 목록 다시 읽기 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-202#loading | 만들기 단추와 줄 세 개 자리 회색 | |
| SCR-202#normal | 위 '새 링크 만들기', 칩 '열림'(골라짐)·'전체', 열린 줄만. 줄은 세 줄: '종류 · 메모', 상태, 날짜 줄(usage-limit의 이름표) | API-240#200 |
| SCR-202#all | 칩 '전체': 네 상태 모두. 쓴 줄은 '씀(쓴 사람)', 기간 지남·거둠 줄은 흐림 | API-240#200 |
| SCR-202#invite-open | usage-limit SCR-169#invite-open 그대로 | API-240#200(`state=open`) |
| SCR-202#invite-used | usage-limit SCR-169#invite-used 그대로 | API-240#200(`state=used`) |
| SCR-202#invite-expired | usage-limit SCR-169#invite-expired 그대로 | API-240#200(`state=expired`) |
| SCR-202#invite-revoked | usage-limit SCR-169#invite-revoked 그대로 | API-240#200(`state=revoked`) |
| SCR-202#open-empty | '열린 초대 링크가 없어요'와 '전체 보기' | API-240#200(열린 줄 없음) |
| SCR-202#empty | '만든 초대 링크가 없어요'(지금 #invites-empty 문구) | API-240#200(빈 목록) |
| SCR-202#creating | 지금 SCR-169#creating 그대로(종류 칩, 사람 고르기, 메모, '만들기') | |
| SCR-202#prefilled | #creating이 열린 채 질의의 종류와 사람이 골라져 있음 | 질의 `?kind=link|relogin&friend=` |
| SCR-202#created | 지금 SCR-169#created와 usage-limit의 '만료 …(7일 뒤)' 그대로 | API-235#201 |
| SCR-202#invite-invalid | 지금 SCR-169#invite-invalid 그대로 | API-235#400(`invalid_input`) |
| SCR-202#member-missing | 지금 SCR-169#member-missing 그대로 → API-236 다시 | API-235#404(`not_found`) |
| SCR-202#revoke-confirm | (제안) 줄 아래 '이 링크를 거둬요. 받은 사람이 열어도 쓸 수 없어요'와 '거두기'·'그만두기' | |
| SCR-202#revoked-now | (제안) 그 줄이 '거둠'과 '만든 때 · 거둔 때 …'로 바뀌고 띠 '링크를 거뒀어요'. 칩 '열림'이면 줄이 빠짐 | API-281#200 |
| SCR-202#invite-closed | (제안) 띠 '이미 쓰였거나 기간이 지난 링크예요'와 목록 다시 읽기 | API-281#409(`invite_closed`) |
| SCR-202#error | 공통#error | API-240#500·503, API-235#403(`cross_site`)·500, API-281#403(`cross_site`)·500·503 |

## 6. 지금 SCR-169 상태가 가는 곳

지금 관리자 화면(한 장)의 상태와 문구는 아래 새 상태로 옮겨요. 문구는 그대로예요. 동희님이 [기능 변경 목록](../02-prd/admin.md#승인된-항목이-바뀌는-곳기능-변경-목록) 5·6을 '바꿈'으로 답하시기 전까지 unified·usage-limit 문서의 표는 고치지 않아요.

| 지금(문서) | 새 상태 |
| --- | --- |
| SCR-169#loading(unified) | SCR-169#loading, SCR-200#loading, SCR-202#loading |
| SCR-169#normal(unified, usage-limit '바뀜') | 초대 링크 그룹 → SCR-202#normal, 가입한 사람 그룹 → SCR-200#normal, 기본 한도 줄 → SCR-200#normal, 그림 예산 비율(SPEC-380) → SCR-169#cards·SCR-204#normal |
| SCR-169#invites-empty | SCR-202#empty |
| SCR-169#members-empty | SCR-200#empty |
| SCR-169#creating, #created, #invite-invalid, #member-missing | SCR-202의 같은 이름 상태 |
| SCR-169#revoke-confirm, #revoked | SCR-201#revoke-confirm, #revoked |
| SCR-169#ticket, #ticket-invalid, #ticket-added | SCR-201의 같은 이름 상태 |
| SCR-169#invite-open, #invite-used, #invite-expired, #invite-revoked(usage-limit) | SCR-202의 같은 이름 상태 |
| SCR-169#limit-unlimited, #limit-default, #limit-custom(usage-limit) | SCR-200#normal과 SCR-201#normal의 '한도 · …' 줄 |
| SCR-169#call-month-unknown(usage-limit) | SCR-201#call-month-unknown, SCR-204#person-unknown |
| SCR-169#limits-edit, #limits-custom, #limits-saving, #limits-saved, #limits-invalid, #limits-missing(usage-limit) | SCR-201의 같은 이름 상태(#limits-missing은 SCR-201#missing) |
| SCR-169#error(unified, usage-limit '늘어남') | 공통#error |
| (없던 상태) SCR-169#forbidden(pet-app SCR-186#forbidden이 가리킴) | 공통#forbidden |

## 7. SCR-203 앱 버전

Purpose: 새 버전을 올린 뒤 폰마다 받았는지, 어디서 멈췄는지 보고, 버전 기록과 릴리스 노트를 읽어요. 읽기만 해요. (FL-201, REQ-577·578)

| Data | Source |
| --- | --- |
| 최신 릴리스(버전 이름·코드, 올린 때), 멈춤 | API-267 `latest`, `paused` |
| 폰(친구 이름, 친구 ID, 폰 순번, 앱 버전, 뒤처짐, 마지막 보고, 알림 권한, 업데이트 기록 20줄). 친구마다 최근 20대, 모두 200대까지 | API-267 `devices` |
| 친구마다 받아 감 20줄(100명까지). 폰 줄과는 `friendId`로 맞춰요 | API-267 `fetches` |
| 버전 기록(올림·멈춤·다시 켬, 릴리스 노트, 기록에서 채움) | API-267 `releases` |

| Action | Result | Failure |
| --- | --- | --- |
| 폰 줄 누름 | 그 줄이 펼쳐져 기록이 보임(#device-open). 다시 누르면 접힘 | 없음 |
| 주소 조각 `#friend={friendId}`로 들어옴 | 그 `friendId`의 첫 폰 줄로 스크롤하고 펼침 | 그 `friendId`의 폰 없음, 숫자가 아님 → 맨 위 그대로 |
| 다시 해 볼게요 | API-267 다시 | 공통#error |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-203#loading | 맨 위 줄, 폰 줄 둘, 기록 줄 셋 자리 회색 | |
| SCR-203#normal | 맨 위 '최신 0.3.3(11) · 11월 24일 오후 2:00에 올림'. 그룹 '폰': 뒤처진 폰이 먼저, 줄마다 '현경 · 폰 1', '0.3.2 · 뒤처짐'(빨간 표) 또는 '0.3.3', '마지막 보고 11월 24일 오후 2:03', 알림이 꺼졌으면 '알림 꺼짐'. 그룹 '버전 기록': 새것부터 '0.3.3(11) 올림 · 11월 24일 오후 2:00'과 그 아래 릴리스 노트 | API-267#200 |
| SCR-203#paused | 맨 위에 노란 띠 '업데이트 멈춤 중 · 폰이 새로 받지 않아요'. 단추 없음 | API-267#200(`paused=true`) |
| SCR-203#device-open | 펼친 줄 아래 기록 줄(명세 3.6의 문구, 새것부터)과 같은 친구의 받아 감 줄. 마지막 상태가 '확인 창 기다림'이면 그 줄이 굵고 '앱을 열어 지금 설치를 눌러야 해요' | API-267#200 |
| SCR-203#backfilled | 버전 기록 줄 끝에 회색 표 '기록에서 채움'. 크기·SHA-256이 없는 줄은 그 칸을 그리지 않음 | API-267#200(`backfilled=true`) |
| SCR-203#no-release | '아직 올린 버전이 없어요' | API-267#200(`latest=null`, `releases` 빈 목록) |
| SCR-203#no-devices | 폰 그룹 '90일 안에 보고한 폰이 없어요' | API-267#200(`devices` 빈 목록) |
| SCR-203#unknown-value | 모르는 `kind`·`state`는 그 값 이름 그대로 한 줄 | API-267#200(목록 밖의 값) |
| SCR-203#same-name | `friendId`가 다른데 이름이 같은 친구가 둘 이상이면 그 이름 뒤에 번호를 붙여 '현경(7) · 폰 1'처럼 보여요 | API-267#200 |
| SCR-203#cap | 폰이 20줄인 친구의 마지막 줄 아래 '이 사람은 최근 보고한 20대만 보여요'. `devices`가 200줄이면 폰 그룹 맨 위에 '폰이 많아 200대까지만 보여요', `fetches`가 100칸이면 '받아 간 사람이 많아 100명까지만 보여요'(회색 글) | API-267#200(상한에 닿음, PR #101 SPEC-438) |
| SCR-203#error | 공통#error | API-267#503(`db_unavailable`), API-267#500 |
| SCR-203#forbidden | 공통#forbidden | API-267#403(`not_allowed`) |

설치 ID, FCM 설치 ID, APK 파일 이름은 API-267에 없어서 이 화면에도 없어요. 릴리스 노트, 친구 이름처럼 사람이 쓴 글은 `textContent`로만 넣어요(명세 1절 8).

API-105의 새 폰 상한(409 `too_many_devices`)은 PR #101의 D134(2026-11-23 승인, PR #101 기능 명세 8.9)예요. 거절된 폰은 줄이 만들어지지 않아서 이 화면에 나오지 않아요. 이 part는 그 동작을 정하지 않아요.

## 8. SCR-204 비용

Purpose: 이번 달 통화 비용이 월 예산의 어디쯤인지, 누가 얼마나 썼는지, 그림 비용이 얼마인지 봐요. (FL-200, REQ-579·520·451)

| Data | Source |
| --- | --- |
| 이번 달 통화 합·월 예산·비율·상태(UTC 달) | API-280 `callMonth` |
| 사람마다 이번 달 통화 비용 | API-236 `members[].callMonthUsd` |
| 그림 비용 종류별(일기·화두·반응·캐릭터)과 예산(한국 시각 달) | API-266 |

| Action | Result | Failure |
| --- | --- | --- |
| 사람 줄 누름 | SCR-201 | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-204#loading | 그룹 셋 자리 회색 | |
| SCR-204#normal | 그룹 '통화 · 11월(UTC)': '$121.40 / $150.00 · 80%'와 막대, 상태 '정상'·'80% 넘음'·'다 씀'·'120% 넘음'. 그룹 '사람마다 통화': 큰 차례로 '이름 · $1.23'. 그룹 '그림 · 11월': 넷 줄 '일기 $2.00', '화두 $0.50', '반응 $0.10', '캐릭터 $3.00 / $20.00 · 15%' | API-280#200, API-236#200, API-266#200 |
| SCR-204#call-warn | 막대와 비율이 노랑(`warn`) | API-280#200(`state=warn`) |
| SCR-204#call-danger | 막대와 비율이 빨강(`danger`), 아래 '새 통화가 막혀요' | API-280#200(`state=exhausted`·`hard_stop`) |
| SCR-204#budget-off | '$30.00 · 예산 꺼짐', 막대 없음 | API-280#200(`state=off`) |
| SCR-204#call-unknown | 통화 그룹만 '지금 못 불러왔어요' | API-280#200(`callMonth=null`) |
| SCR-204#person-unknown | 그 사람 줄 '이름 · —' | API-236#200(`callMonthUsd=null`) |
| SCR-204#images-unknown | 그림 그룹만 공통#error | API-266#500·503 |
| SCR-204#error | 공통#error | API-280#500·503, API-236#500·503 |
| SCR-204#forbidden | 공통#forbidden | API-280#403, API-236#403, API-266#403 |

## 9. SCR-186 아이템

[pet-app.md](pet-app.md)의 SCR-186 정의 그대로예요. 바뀌는 곳은 위에 공통 탭 줄이 생기는 것 하나예요(지금 탭 '아이템'이 골라짐). 이번 달 그림 비용 줄은 SCR-169 카드와 SCR-204로 가요(기능 변경 목록 10). SCR-186#forbidden은 공통#forbidden이에요.

## 10. 확인

- 모든 데이터가 API를 가리켜요. API-280·281·235\~243·263\~267의 응답마다 위 상태 하나가 있어요(API-267의 응답 200·403·500·503은 PR #101 계약 기준).
- 모든 동작에 결과와 실패가 있어요.
- 긴 글: 메모 40자, 이름 12자, 릴리스 노트 300자는 줄바꿈해 모두 보이고(글은 `textContent`로만), 360px에서 숫자 카드의 글이 두 줄이 되어도 자리가 넘치지 않아요.
- 와이어프레임은 위 상태마다 한 칸이에요(공통 상태는 한 번만). 360px와 430px를 나란히 그렸어요.
