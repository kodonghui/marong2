# 기본 마롱이 차림 통화 화면 반영 기록

- 승인: 2026-11-28 주말 위임에 따른 항목 253. 스위치는 0을 유지했어요.
- 기록 PR #149: 리뷰 확인 head `409df53452ad18982fd326b7477413f8b867e99b`, 병합 `b852d62e0351bf0cf4b5396249cfbbec06e2ce85`.
- BASE 정정: 최초 지시는 PR #149 병합 직전 main을 BASE로 지정했으나, 담당자가 2026-11-28 Orca 메시지 `msg_0d630b7eaf12`에서 PR #148 병합 직전 main `0cf4e09fb72d6a15edf70dbd79884c3d5b7cbe94`로 바로잡았어요. `4c8d786`은 이미 변경을 포함하므로 그 해시 불일치로 한 번 중단한 뒤 정정받았어요.
- 백업과 되돌리기: `/home/opc/marong-deploy/20261128-wear-call-253/before/`, `/home/opc/marong-deploy/20261128-wear-call-253/rollback.sh`. 두 운영 파일은 정정된 BASE와 일치했어요. 후보 두 파일은 `4c8d786`과 최신 main에서 같았어요.
- SHA-256: 이전 `app.js` `30dd45e1b30e0d984221a9403d9428cd98ab75ca585ccf86a311102e927f86dc`, 이전 `style.css` `3d979006ee156d90b6a15ad4ac8b1a9a672a8e89ec5190c64527192c5e63f8f7`. 반영 후 각각 `6ef873ed5917e86f68eb41d5eef8c1be19deaead7c7273a3116e448f3e704d62`, `80d7aca446ac876121aa493c835c6c2e65cf2fc43d2e037d13b316dd7c79e973`.
- 재시작 전 `call.calls` 미종료 및 서버 TCP 연결은 12:28:31 UTC와 12:29:45 UTC에 각각 0건이었어요. 두 번째 확인과 파일 재대조 뒤 교체하고 12:29:45 UTC(21:29:45 KST)에 사용자 유닛 `marong-vertex-live`를 재시작했어요.
- 관찰: 재시작부터 12:34:56 UTC(21:34:56 KST)까지 5분 11초 동안 서비스 `active`, 자동 재시작 0건, 오류 우선순위 로그 0건, 오류 문구 검색 0건을 확인했어요. 로컬 포트 8792 LISTEN과 HTTP 302 응답을 확인했어요. 실제 통화와 실제 폰 시험은 실행하지 않았어요.
- 남은 일: 별도 승인된 스위치 1 전환과 그 뒤 실제 폰 TC-769 확인.
