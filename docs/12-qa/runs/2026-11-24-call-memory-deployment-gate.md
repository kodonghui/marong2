# PR #119 통화 기억 운영 반영과 복구

- **운영 반영 및 카드 숨김 완료.** 2026-11-24 03:53:25 KST에 두 서비스가 새 프로세스로 시작했고, 03:58:28 KST에 302초 검증을 마쳤다. 03:58:53 KST에 카드 두 건을 숨겼다.
- 병합 2026-11-24 03:37:17 KST. PR #119의 검토 대상 `701d6d5764b92a34fd6aaa1198d299d4a0ab2c89`를 병합 커밋 `5f89fd542f1ddd5d832e89635d6a6fae65997f01`으로 합쳤다. 리뷰 요청 한 건은 사용 한도로 실패해 기존 리뷰로 병합을 판단했다. [PR #119](https://github.com/kodonghui/marong2/pull/119), [기존 리뷰](https://github.com/kodonghui/marong2/pull/119#issuecomment-7110352271), [병합 판단 기록](https://github.com/kodonghui/marong2/pull/119#issuecomment-7110417544)
- 운영 사전 대조 2026-11-24 03:37:54 KST. `ko-family`의 통화 서버 작업 폴더 `/home/opc/marong-deploy/20261119-unified-cutover.qAcbv7Wm/voice-runtime/tools/vertex_live/`와 승인 기준 `85567b18274170cdcc563ef57155cc1bd720273a`의 같은 폴더를 파일별 SHA256으로 대조했다. 병합 전 `main`인 `ad7226b`와도 대조해 기존 차이를 확인했다.
- **1차 사전 대조 중단.** 승인 범위 밖 파일의 차이로 배포 전 단계에서 중단했다. 당시 파일 교체, 유닛 변경, 재시작, 데이터 변경은 0건이었다. 이후 런타임 파일 6개에 한해 반영하기로 했다.

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
| TC-644 · BUG-117 | 격리 회귀 1건 통과. 설정 동등성 확인 후 14:34:52 KST 반영, 303초 로그에서 오류와 `call_tuning_fallback` 각 0건. 첫 웹 통화 대기. |
| TC-645 · BUG-118 | 반영. 운영 지시문 SHA256이 승인본과 `main`에 일치했다. |
| TC-646~648 · BUG-119~121 | 반영. 격리 회귀, 승인본 6개 해시, import, 서비스 302초 확인 통과. 실통화 확인 대기. |
| TC-649 · BUG-122 | 반영. 정리기가 승인 파일을 둔 배포 폴더에서 실행됐고 302초 동안 두 서비스가 `active`였다. |

03시대 BUG-118~122 반영에서는 승인된 `85567b1`의 `live_session.py`를 사용했다. 14시대 BUG-117 반영 뒤에는 운영과 최신 `main`의 파일 해시가 같다.

카드 두 개의 숨김은 마롱이 항목 77(2026-11-24 03시대 KST)에서 승인됐다. [실행 결과와 복구 명령](#카드-두-건-숨김)

| 파일 | 사전 대조의 운영 SHA256 | 승인 커밋 SHA256 | 병합 후 `main` SHA256 |
| --- | --- | --- | --- |
| `live_session.py` | `8bab5a2465d036e40b9b26b82c4fa16f386e6709e48467788b2fd88406a592d6` | `223b81253363c353a60ee34055cd90785255c09c13716eb44619dce2f031567b` | `961fc4cc8fd4c14d119d516b6e316a5d032fa773ea2892650bb1409bddc89060` |
| `call_instruction.md` | `a8ea9de577861edde03dd2e00bb70f23544dbf24d459e6969dfbc9ec3d8d4e73` | `119bd8baf8e682054162cac29007875ecb65aa29d994268e33a139a88bab1800` | `119bd8baf8e682054162cac29007875ecb65aa29d994268e33a139a88bab1800` |

## 런타임 6개 승인 후 반영 시도와 복구

2026-11-24 03:44:06 KST `ko-family`에서 승인된 런타임 파일을 다시 대조했다. 배포 폴더의 파일을 병합 전 `main`인 `ad7226b`의 같은 파일과 비교한 결과다.

| 파일 | SHA256 대조 결과 |
| --- | --- |
| `call_instruction.md` | 다름. 운영 해시가 구버전 `a2dc9a0`과 일치했다(BUG-118). |
| `call_memory.py` | 일치 |
| `live_session.py` | 일치 |
| `memory_tools.py` | 일치 |
| `organizer.py` | 일치. 실행 중인 정리기는 이 사본 대신 `/home/opc/marong-vertex-test/app/organizer.py`를 사용했다(BUG-122). |
| `server.py` | 일치 |

- 반영 직전 DB 열린 통화 0건, 최근 3분 `last_beat_at` 0건, 미완료 정리 작업 0건, 통화 서버 연결과 관련 로그 이벤트 각각 0건이었다. 서버 안에 6개 파일과 두 유닛 설정, DB를 백업했다. DB 백업은 27,276,457바이트이며 `pg_restore -l`에서 788줄을 확인했다. [백업 및 복구 명령](#서버-백업과-복구-명령)
- 임시 반영한 운영 파일 6개 모두 `85567b1`과 SHA256이 일치했고, 새 정리기와 통화 서버 모듈 import를 통과했다. 정리기의 반영 설정에는 릴리스 경로와 기존 통화 서버의 의존성 경로를 지정했다.
- 03:47:39 KST에 `systemd-analyze --user verify marong-voice-memory.service`가 `Failed to initialize manager: No such device or address`와 종료 코드 1을 반환했다. 재시작 전에 파일 6개를 복원하고 적용하려던 drop-in을 백업 폴더로 옮긴 뒤 사용자 유닛 설정을 다시 읽었다. 복구 명령의 출력은 `ROLLBACK_COMPLETE`였다. 시험 파일과 표정 이미지는 기존 파일을 유지했다.
- 03:48:17 KST 재조회에서 6개 파일 모두 반영 전 해시와 일치했다. 통화 서버 PID `440904`와 정리기 PID `3187623` 모두 이전과 같고 `active`였으며, 각 서비스의 자동 재시작은 0회였다. 통화 서버의 로컬 `/healthz`는 HTTP 200을 반환했다. 정리기의 실행 경로는 복구 전부터 사용한 `/home/opc/marong-vertex-test/app/organizer.py`다.
- SSH 실행 환경에 `XDG_RUNTIME_DIR` 값이 없었다. 복구된 유닛을 읽기 검증한 결과 기본 환경은 종료 코드 1, 사용자 런타임 경로와 버스 주소를 명시한 환경은 종료 코드 0을 반환했다. 새 drop-in의 검증, 서비스 재시작과 반영 뒤 5분 로그 확인은 다음 반영 때 수행한다.
- 이 시도의 BUG-118~122 운영 반영은 복구로 종료됐다. 당시 카드 숨김과 BUG-117 반영은 대기 상태였다.

### 서버 백업과 복구 명령

서버 백업 경로는 `/home/opc/marong-deploy/20261124-bug118-122.Ioj1ff/backup/`이다.

```bash
bash /home/opc/marong-deploy/20261124-bug118-122.Ioj1ff/deploy.sh rollback
```

## 사용자 런타임과 버스를 지정한 재반영

- 2026-11-24 03:52:39 KST에 사전 대조를 반복했다. 지시문은 확인된 구버전 `a2dc9a0`과 일치했고, 나머지 5개 파일은 병합 전 `ad7226b`와 일치했다. 운영 파일 교체 전에 사용자 런타임과 버스 경로를 지정한 환경에서 임시 정리기 유닛 검증이 통과했다.
- 새 백업은 서버의 `/home/opc/marong-deploy/20261124-bug118-122-retry.hPaIjN/backup/`에 있다. 파일 6개, 유닛 설정과 DB를 보관했다. DB 백업은 27,276,457바이트이며 `pg_restore -l`은 788줄을 반환했다. 파일 교체 전에 복구 명령을 확인했다.
- 파일 교체 뒤 `85567b1`의 SHA256 6개, 새 모듈 import 및 설치한 정리기 유닛 검증이 통과했다. 열린 통화, 최근 3분 신호, 미완료 정리, 연결과 통화 로그 이벤트는 재시작 직전 모두 0건이었다. 시험 파일과 운영 표정 이미지는 기존 파일을 유지했다.
- 두 서비스의 `ActiveEnterTimestamp`는 03:53:25 KST다. 03:53:26 KST에 통화 서버 PID `449003`, 정리기 PID `448999`, 두 서비스 `active` 및 로컬 HTTP 200을 확인했다. 정리기는 `/home/opc/marong-deploy/20261119-unified-cutover.qAcbv7Wm/voice-runtime/tools/vertex_live/organizer.py`로 전환됐다.
- 03:58:28 KST에 302초 검증을 통과했다. 유닛 필터로 조회한 로그 8줄에서 오류 0건이었다. 두 PID와 `active` 상태, HTTP 200, SHA256 6개가 유지됐고 자동 재시작은 0회였다. 03:53:26~03:58:53 KST에 시작된 통화는 0건이어서 실통화 검증은 대기 중이다.
- 이 시점의 운영 `live_session.py`는 승인된 `85567b1`의 해시 `223b81253363c353a60ee34055cd90785255c09c13716eb44619dce2f031567b`였다.

```bash
bash /home/opc/marong-deploy/20261124-bug118-122-retry.hPaIjN/deploy.sh rollback
```

### 카드 두 건 숨김

- 서비스 검증 통과 뒤 03:58:53 KST에 실행했다. 대상 두 행을 운영 서버의 `/home/opc/marong-deploy/20261124-bug118-122-retry.hPaIjN/backup/cards-before-hide.csv`에 백업하고 CSV의 행 수 2개를 확인했다.
- UTC `marker`는 `2026-11-23T18:58:53.324029Z`다. SQL 출력은 `changed_cards=2`였으며 읽기 조회는 `targets|marker_matches=2|2`를 반환했다.
- 카드 복구는 같은 `marker`를 사용한다.

```bash
sudo -n -u postgres psql -X -d marong -v action=restore -v marker=2026-11-23T18:58:53.324029Z -f - < /home/opc/marong-deploy/20261124-bug118-122-retry.hPaIjN/card-hide.sql
```

## BUG-117 설정 동등성 검증과 운영 반영

- 마롱이 항목 77(2026-11-24 KST)에서 기존 기본값과 운영 구간 설정의 일치를 조건으로 BUG-117의 반영을 승인했다. `85567b1`과 당시 `main` `437a17a1a78b72a85c7da995e7350e5a5a25b871` 사이에 바뀐 런타임 파일은 `tools/vertex_live/live_session.py` 한 개였다. 운영 파일의 반영 전 SHA256은 `85567b1`의 `223b81253363c353a60ee34055cd90785255c09c13716eb44619dce2f031567b`였다.
- 14:28:13 KST에 운영 venv에서 외부 연결을 막고 `server.setup()`을 두 번 호출했다. `tuning=None`과 운영 DB의 `base-20261116` 행을 입력한 결과다. 실제로 선택된 행도 `base-20261116`이었다.

| 비교 항목 | `tuning=None` | `base-20261116` |
| --- | --- | --- |
| `generationConfig.maxOutputTokens` | 1,024 | 1,024 |
| `realtimeInputConfig.automaticActivityDetection` | `prefixPaddingMs=100`, `silenceDurationMs=700` | 동일 |
| `contextWindowCompression` | `triggerTokens=8192`, `slidingWindow.targetTokens=4096` | 동일 |
| `seed()`의 `memory_limit` 및 행의 `seed_call_memories` | 30 | 30 |

세 setup 항목은 객체 비교에서 일치했다. TC-644 격리 회귀 시험 한 건도 통과했다. 운영 파일 백업은 `/home/opc/marong-deploy/20261124-bug117.mJE8w8/backup/live_session.py`에 있다.

```bash
bash /home/opc/marong-deploy/20261124-bug117.mJE8w8/deploy.sh rollback
```

- 사전 조회의 `resting` 통화 1건은 연결과 열린 구간이 0개였다. `server.py`가 재연결 상태에 사용하는 600초가 지난 뒤에도 `live` 0건, 최근 10분 `resting` 0건, 최근 3분 신호 0건, 열린 구간 0건을 확인했다. 이전 `resting` 행은 유지했다.
- `live_session.py` 한 파일을 교체하고 승인본 해시와 운영 venv의 import를 확인했다. 재시작 직전 위 조건을 다시 확인했다. 통화 서버의 `ActiveEnterTimestamp`는 14:34:52 KST였고, 14:34:53 KST에 새 PID `508621`의 `active` 상태와 HTTP 200을 확인했다.
- 14:39:56 KST에 303초 검증을 마쳤다. 통화 서버는 같은 PID로 `active`였고 자동 재시작 0회, HTTP 200이었다. 통화 서버 유닛 로그 4줄에서 오류와 `call_tuning_fallback`은 각각 0건이었다. 구간 조회는 `waiting_for_first_call`을 반환해 첫 웹 통화 대기로 기록했다.
- 운영 파일과 최신 `main`(`def10ad8bac0d554f8b2dfa71e804996dd6873d0`)의 `live_session.py` SHA256은 모두 `961fc4cc8fd4c14d119d516b6e316a5d032fa773ea2892650bb1409bddc89060`이었다. 운영 구간 설정은 `base-20261116`을 사용한다.
