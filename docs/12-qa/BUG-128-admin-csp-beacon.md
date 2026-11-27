# BUG-128 · 관리 화면에서 통계 스크립트 CSP 차단 콘솔 오류

- 상태: open (수정 PR 검토 중, 운영 미반영) · 심각도 S3 · 우선순위 P3 · 유형: 구현 · 원인 단계: 11 개발
- 발견: 2026-11-27 운영 읽기 전용 화면 걷기, TC-639 · SPEC-450 · SCR-169·200~204·186·220
- 재현: 관리자 인증 뒤 `/chat/admin/` 아래 화면을 열어 브라우저 콘솔을 확인해요.
- 기대: 화면을 열 때 콘솔 오류가 없어요.
- 실제: Cloudflare 통계 스크립트 `beacon.min.js` 요청이 `script-src` 콘텐츠 보안 정책에 차단돼 콘솔 오류가 나요. 헤드리스 Chromium과 WebKit에서 일곱 화면 모두 재현했어요. 아이템 API의 404는 꺼진 꾸미기에 대해 예상한 응답이며 별도예요.
- 영향: 관리 화면과 주요 읽기 API의 불러오기 실패는 없었어요. 운영의 `/chat/`을 비로그인 GET하면 `/chat/login`으로 이동하는데, 그 로그인 화면에도 같은 beacon CSP 오류가 있어요(Chromium). 친구로 로그인한 뒤의 대화 화면은 확인하지 않았고, 친구 화면 변경은 이번 수정에 포함하지 않아요.
- 원인: 앱의 관리 HTML 응답은 `no-store`만 보내고 Cloudflare의 자동 HTML 변경을 막지 않았어요. Cloudflare는 응답을 거치며 Web Analytics 스크립트를 넣는데 앱의 기존 CSP는 이를 허용하지 않아요. 문서의 화면 오류 없음 기준과 구현의 차이로 11 개발에 두며 설계 문서는 바꾸지 않아요. [Cloudflare의 Web Analytics FAQ](https://developers.cloudflare.com/web-analytics/faq/)는 `no-transform`이 자동 beacon 삽입을 막는다고 설명하고, [응답 본문 검사 설명](https://developers.cloudflare.com/rules/configuration-rules/response-body-inspection/)도 Web Analytics가 지원 대상이며 해당 지시어가 본문 변경을 막는다고 설명해요.
- 수정: 관리 HTML 응답에 기존 `no-store`와 함께 `no-transform`을 붙여요. 관리 API와 친구 화면의 캐시 헤더, CSP는 그대로예요. 관리 HTML의 200·403·404를 모두 다뤄요.
- 회귀 확인: `TC-729 (`tests/test_admin.py AdminChangesTest.test_tc729_bug128_admin_html_prevents_edge_transform`)`은 수정 전 `150f186`에서 관리 HTML 열 응답의 헤더가 `no-store`여서 10개 하위 검사에 실패했고, 수정 후 관리 화면 여덟 경로와 403·404 및 관리 API·친구 로그인 경계 확인이 통과했어요. 운영에서의 beacon 제거는 반영 후에만 확인할 수 있어요.
- 놓친 이유: TC-639 이전 확인에서 인증 세션이 없어 브라우저 콘솔을 걷지 못했고, 관리 HTML 헤더 시험에는 Cloudflare 자동 삽입을 막는 조건이 없었어요. TC-729와 TC-639의 콘솔 확인으로 보완해요.
- 반영 후 확인: 관리자 인증 후 일곱 화면을 Chromium·WebKit에서 GET하여 HTML 응답에 `no-store, no-transform`이 있는지, beacon 스크립트가 삽입되지 않는지와 콘솔 오류 0건인지 확인해요. 실제 Cloudflare 경유 결과와 TC-639 판정은 그때 기록해요.
