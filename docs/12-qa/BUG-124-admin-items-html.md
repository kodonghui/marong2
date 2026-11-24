---
id: BUG-124
title: 꾸미기를 끈 환경에서 관리자 아이템 탭이 404 JSON을 반환함
status: fixed
severity: S3
priority: P1
found_in: production
defect_type: Implementation
cause_stage: "11"
---

# BUG-124 관리자 아이템 페이지에 404 JSON이 표시됨

- 발견은 2026-11-24 KST 사용자님 보고(마롱이 항목 3, TC-639)예요. 배포 기준은 `ad7226b`이고 사용 기기는 확인되지 않았어요.
- 영향 범위는 관리자 아이템 탭이에요. 같은 시험용 관리자 JWT로 개요·회원·회원 상세·초대 링크·앱 버전·비용 여섯 경로에서 200 HTML을 확인했어요.

## 원인과 재현

꾸미기가 꺼진 앱 서버에서 친구 계정이 연결되지 않은 시험용 관리자 Access JWT로 `GET /chat/admin/items`에 접근해요. `AppAdmin.page`가 관리자 인증을 마친 뒤 아이템 목록 설정을 검사해, HTML 렌더링 전에 404 `application/problem+json`을 반환해요. 응답의 `/problems/not-found`, `not_found`, ‘이 계정으로 찾을 수 없음’이 보고와 일치했어요.

운영에서 실행 중인 `marong-app.service`는 꾸미기 설정이 비활성이었고 아이템 목록 파일은 있었어요. Cloudflare 터널의 이 경로는 앱 서버의 8797 포트로 이어졌어요. 보고된 추적 ID는 앱·봇·프록시·터널 로그에서 각각 0건이었어요. 앱의 요청 로그는 꺼져 있고, 예상된 `Problem` 응답은 예외 로그를 남기지 않는 코드 경로였어요.

## 회귀 기준과 누락 이유

SPEC-450·SCR-186은 관리자 화면에 200 HTML과 공통 탭을 요구해요. SPEC-417과 API-263~265는 꾸미기를 끈 경우 아이템 API의 404를 유지해요. 11단계 구현에서 API의 카탈로그 조건을 화면에도 적용했어요. 승인된 명세는 유지하고 기존 SCR-186 오류 상태를 사용해요.

TC-620은 카탈로그가 있는 환경을, TC-638 브라우저는 가짜 화면 응답을 검사했어요. TASK-500의 운영 점검은 비인증 상태였어요. TC-652에서 카탈로그가 없는 환경의 인증된 화면과 기존 API 응답을 같이 검사해요. 운영 관리자로 보는 TC-639는 후속 확인이에요.

## 수정과 시험 결과

`AppAdmin.page`에서 아이템 HTML의 카탈로그 검사를 빼고, 기존 인증과 공통 탭을 사용해요. 카탈로그 없이 API를 호출하면 404가 돌아오고, 아이템 화면에 기존 불러오기 오류와 ‘다시 보기’ 단추가 표시돼요.

수정 전 기준 `437a17a`에서 TC-652를 돌리면 아이템 경로가 404 JSON을 반환해 1개 실패했어요(`FAILED (failures=1)`). 수정 뒤 WSL Python 3.12와 임시 PostgreSQL에서 TC-620·621·652 3개와 꾸미기 회귀 시험 4개가 통과했어요. 시험용 Access JWT로 화면 7개에 200 HTML, 아이템 API 3개에 404, 비인증 아이템 화면에 403을 확인했어요.

## 운영 반영

- [PR #125](https://github.com/kodonghui/marong2/pull/125)의 병합 커밋은 `def10ad8bac0d554f8b2dfa71e804996dd6873d0`이에요. 2026-11-24 14:33:18 KST에 `marong/app_admin.py` 한 파일을 반영하고 `marong-app.service`를 재시작했어요. 교체 전 파일의 SHA256은 병합 전 `main`(`437a17a`)과 일치했어요.
- 병합 커밋에서 TC-652를 다시 돌렸어요. 임시 PostgreSQL에서 `Ran 1 test`와 `OK`를 확인했어요.
- 재시작 직전 글 대화 로그와 DB의 최근 3분 글 대화가 각각 0건이었고, 진행 중 통화와 웹 통화 연결은 각각 0건이었어요. 오래된 `resting` 행 1건은 3분 넘게 신호가 없고 열린 구간과 웹 연결이 없음을 확인했어요.
- 반영 뒤 서비스 `active`, `/chat/healthz` 200, 비인증 로컬 `/chat/admin/items` 403, 5분 로그의 `ERROR` 0건을 확인했어요. 운영 파일의 SHA256 `2cdf44c12bf37b53beeb9610475b8015c7249d219b154c90b4ef6a9072f9ff39`가 병합 커밋과 일치했어요.
- 파일 백업은 `~/marong-deploy/20261124-bug-124.UCXbGqeu/app_admin.py.before`예요. 되돌리는 명령은 `bash ~/marong-deploy/20261124-bug-124.UCXbGqeu/rollback.sh restart`예요.
- 운영 관리자 화면을 실제 기기에서 보는 TC-639는 사용자님 확인 대기예요.
