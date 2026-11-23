# PR #119 통화 기억 운영 반영 사전 대조

- 병합 2026-11-24 03:37:17 KST. PR #119의 검토 대상 `701d6d5764b92a34fd6aaa1198d299d4a0ab2c89`를 병합 커밋 `5f89fd542f1ddd5d832e89635d6a6fae65997f01`으로 합쳤다. 리뷰 요청 한 건은 사용 한도로 실패해 기존 리뷰로 병합을 판단했다. [PR #119](https://github.com/kodonghui/marong2/pull/119), [기존 리뷰](https://github.com/kodonghui/marong2/pull/119#issuecomment-7110352271), [병합 판단 기록](https://github.com/kodonghui/marong2/pull/119#issuecomment-7110417544)
- 운영 사전 대조 2026-11-24 03:37:54 KST. `ko-family`의 통화 서버 작업 폴더 `/home/opc/marong-deploy/20261119-unified-cutover.qAcbv7Wm/voice-runtime/tools/vertex_live/`와 승인 기준 `85567b18274170cdcc563ef57155cc1bd720273a`의 같은 폴더를 파일별 SHA256으로 대조했다. 병합 전 `main`인 `ad7226b`와도 대조해 기존 차이를 확인했다.
- **운영 반영 중단.** 승인 범위 밖 파일의 차이로 배포 전 단계에서 중단했다. 운영 반영 시각은 없다. 파일 교체, 유닛 변경, 재시작, 데이터 변경은 0건이었다.

## 파일 대조

기준 커밋 79개와 운영 파일 96개에서 내용 일치 54개, 내용 다름 21개, 저장소에만 있음 4개, 운영에만 있음 21개를 확인했다. 운영의 생성 캐시 `*.pyc` 46개는 별도로 집계했다.

| 분류 | 경로 (`tools/vertex_live/` 기준) |
| --- | --- |
| 승인 작업의 런타임 파일 6개 | `call_instruction.md`, `call_memory.py`, `live_session.py`, `memory_tools.py`, `organizer.py`, `server.py` |
| 승인 커밋에 포함된 문서·시험 파일 차이 7개 | `OPERATIONS.md`, `test_call_cost.py`, `test_call_report.py`, `test_hangup.py`, `test_memory_bridge.py`, `test_ring.py`, `test_transcript_report.py` |
| 승인 커밋에 포함된 저장소 전용 시험 2개 | `test_call_memory_regressions.py`, `test_connect_server.py` |
| 승인 범위 밖 내용 차이 8개 | `test_fallback.cjs`, `test_hangup_client.cjs`, `test_relay.py`, `test_rtc_api.py`, `test_rtc_watchdog.cjs`, `test_search.py`, `test_unified_call_tools.py`, `test_unified_calls.py` |
| 승인 범위 밖 저장소 전용 시험 2개 | `test_playback_probe.cjs`, `test_web_reconnect.py` |
| 운영 전용 표정 이미지 21개 | 아래 목록 |

```text
static/face/v1/01-neutral.webp
static/face/v1/02-big-laugh.webp
static/face/v1/03-listening.webp
static/face/v1/04-thinking.webp
static/face/v1/05-excited.webp
static/face/v1/06-sad.webp
static/face/v1/07-crying.webp
static/face/v1/08-surprised.webp
static/face/v1/09-pouting.webp
static/face/v1/10-shy.webp
static/face/v1/11-drowsy.webp
static/face/v1/12-asleep.webp
static/face/v1/13-concerned.webp
static/face/v1/15-mouth-slightly-open.webp
static/face/v1/16-mouth-wide-open.webp
static/face/v1/18-eyes-half-closed.webp
static/face/v1/19-eyes-closed.webp
static/face/v1/20-mouth-slightly-open-eyes-half-closed.webp
static/face/v1/21-mouth-slightly-open-eyes-closed.webp
static/face/v1/22-mouth-wide-open-eyes-half-closed.webp
static/face/v1/23-mouth-wide-open-eyes-closed.webp
```

## QA 결과와 후속 반영

| 항목 | 결과 |
| --- | --- |
| TC-644 · BUG-117 | 합침, 운영 반영 보류. 마롱이 항목 77(2026-11-24 03시대 KST)에 따라 대화 이어 주기 설계(항목 78)에서 컨텍스트 창 압축 값을 정한 뒤 반영한다. 원래 PR의 격리 회귀 통과. |
| TC-645 · BUG-118 | 사전 대조에서 운영 지시문 해시 불일치 확인. 파일 교체와 반영 후 일치 확인 대기. |
| TC-646~648 · BUG-119~121 | 병합된 코드의 격리 회귀 통과. 승인 범위 밖 차이로 운영 반영 중단. |
| TC-649 · BUG-122 | 사전 조회에서 통화 서버와 정리기 모두 `active`였다. 정리기의 작업 폴더는 `/home/opc/marong-vertex-test/app`였다. 유닛 전환과 실행 해시 확인 대기. |

5분 로그 검증은 운영 반영 뒤에 수행한다. 다음 통화 서버 반영에서도 승인된 `85567b1`의 `live_session.py`를 기준으로 삼는다. `main`의 파일에는 압축 값 확정 뒤 반영할 BUG-117 변경이 포함돼 있다.

카드 두 개의 숨김은 마롱이 항목 77(2026-11-24 03시대 KST)에서 승인됐다. BUG-118~122 반영과 확인이 선행 조건이라 실행은 대기 중이다. 실행 시각을 정하면 UTC `marker`, 변경 행 수, 확인 결과와 같은 `marker`를 쓰는 복구 명령을 기록한다.

| 파일 | 운영 SHA256 | 승인 커밋 SHA256 | 병합 후 `main` SHA256 |
| --- | --- | --- | --- |
| `live_session.py` | `8bab5a2465d036e40b9b26b82c4fa16f386e6709e48467788b2fd88406a592d6` | `223b81253363c353a60ee34055cd90785255c09c13716eb44619dce2f031567b` | `961fc4cc8fd4c14d119d516b6e316a5d032fa773ea2892650bb1409bddc89060` |
| `call_instruction.md` | `a8ea9de577861edde03dd2e00bb70f23544dbf24d459e6969dfbc9ec3d8d4e73` | `119bd8baf8e682054162cac29007875ecb65aa29d994268e33a139a88bab1800` | `119bd8baf8e682054162cac29007875ecb65aa29d994268e33a139a88bab1800` |
