# 운영 확인: Google 인증과 WebRTC 연결

확인일: **2026-11-13, 한국 시간**. 운영 서버의 실행 중 설정과 소스를 대조하고 통화 중 자동 전환 및 통화 세션 보고를 배포했다. Google 인증과 상시 방화벽 포트는 그대로다. 실제 차단 시험의 임시 패킷 폐기 규칙은 제거했다.

## GitHub에 보관된 변경

- 기준: `6d349f7`, 2026-11-12 **21:50:43 KST**.
- 기억 자동 연결·WebRTC 구현: `ae1b607`, 같은 날 **23:57:50 KST**, 변경 파일 33개.
- 브랜치: `codex/marong-vertex-live`.
- 운영 빌드: `20261113-failover1`. Sulafat 목소리와 한국어 설정 유지.
- 이 문서와 `deploy/`의 서비스·설정 템플릿은 그 뒤에 추가한 운영 기록이다. 실행 파일과 비밀값을 제외한 서버 구성도 함께 보관한다.

사용자 명령으로 저장·삭제하는 기능과 기억 관리 화면은 최종 구현에 없다. 통화 내용을 종료 후 자동 정리하여 다음 카톡 응답에 사용한다.

## Google 연결: API 키 방식

실행 중인 통화 서비스와 자동 정리 서비스 모두 **`VERTEX_AUTH_MODE=api_key`**다. 두 서비스는 서버 안의 `/home/opc/.config/marong-call/gemini2.key`를 읽고 `x-goog-api-key` 헤더로 Google에 보낸다. 파일 권한은 `0600`이다. 값은 출력하거나 다른 기기로 복사하지 않았다.

현재 키는 서비스 계정에 연결된 **Authorization API key** 형식이다. Google 공식 문서도 이 유형을 서비스 계정의 권한으로 동작하는 장기 자격 증명으로 설명한다. [Google API 키 설명](https://docs.cloud.google.com/docs/authentication/api-keys)

**앞서 검토했던 7일짜리 공개 인증서 방식은 사용하지 않는다.** 운영 인증 경로에 `vertex.json`, `vertex-live-public.pem`, `vertex-live.pem`은 존재하지 않는다. 앱과 서비스에 7일 만료나 7일 주기 갱신 설정도 없다. 따라서 그 인증서를 매주 다시 등록할 작업은 없다.

이것이 키의 영구 유효성을 보장하는 뜻은 아니다. Google에서 키를 삭제·차단하거나 연결된 계정의 권한을 바꾸면 인증이 실패할 수 있다. 이번에는 Google 관리 콘솔의 개별 키 메타데이터까지 조회하지 않았다. 무료 크레딧의 유효기간도 인증서·키 갱신과 별개다.

### 교체가 필요할 때

현재는 인증서 연장이 아니라 **API 키 교체** 절차를 쓴다. 다음은 실행 지침이며 이번 확인에서 새 키를 만들거나 이전 키를 폐기하지 않았다.

1. 같은 프로젝트·서비스 계정·API 제한을 유지한 새 Authorization API key를 만든다. Vertex용 `aiplatform.googleapis.com` 허용을 빠뜨리지 않는다. 기존 키가 다른 앱에도 쓰이는지 먼저 확인한다.
2. 키·인증 파일을 기기 사이에 옮기지 않는 운영 원칙에 맞춰, 권한 있는 관리 세션에서 Google API/CLI를 **싱가포르 서버 안에서 실행하여** 새 키를 서버의 임시 파일에 직접 받는다. 기존 키를 명령 인자·URL·로그·Git에 노출하지 않는다. 서버에는 현재 `gcloud`가 설치되어 있지 않으므로 이 절차를 CLI로 수행하려면 서버에서 관리 도구 설치와 로그인이 먼저 필요하다.
3. 같은 디렉터리의 `gemini2.key.next`에 소유자 `opc`, 권한 `0600`을 적용하고 새 키로 실제 Vertex Live 연결과 정리 모델 요청을 확인한다. `/healthz`나 `/status`만으로는 Google 인증 성공을 검증할 수 없다.
4. 시험을 통과한 파일을 서버 내에서 `gemini2.key`로 원자적으로 교체한다. 통화가 없는 시점에 실제 새 통화를 시작해 확인한다. 코드는 Live 재연결과 정리 요청 때 파일을 다시 읽으므로 정기 재발급 데몬은 필요하지 않다. 기존 연결을 즉시 새 키로 바꾸려면 통화가 없을 때 통화·정리 서비스를 재시작한다.
5. 이 키를 사용하는 모든 앱의 전환을 확인한 다음 기존 키를 폐기한다. 새 키 검증에 실패하면 기존 키를 유지한다.

이는 Google의 ‘새 키 발급 → 앱 전환 → 이전 키 삭제’ 순서를 따른다. [Google 키 교체 절차](https://docs.cloud.google.com/docs/authentication/api-keys)

브라우저에 발급되는 LiveKit 수신 토큰의 24시간 TTL은 Google 인증과 별개다. `/api/rtc`에서 새 연결 때 서버가 발급한다. 이 토큰을 Google 키와 혼동하지 않는다.

## 서버 포트

| 포트 | 실제 설정 | 쓰임 |
|---|---|---|
| **7882/UDP** | UFW 외부 허용, IPv4·IPv6 | WebRTC 음성 전송. 단일 UDP 포트를 사용한다. |
| **7881/TCP** | UFW 외부 허용, IPv4·IPv6 | UDP 연결이 안 될 때 시도하는 WebRTC ICE/TCP 경로. |
| **7880/TCP** | **127.0.0.1에만 바인딩**, 외부 미개방 | LiveKit API·시그널링. 앱이 인증을 확인한 뒤 서버 내부로 중계한다. |
| **443/HTTPS·WSS** | 기존 전용 도메인의 Cloudflare 경로 | 웹 페이지, 로그인, 시그널링, 마이크·제어, 대체 PCM 음성. WebRTC 때문에 새로 공개한 포트가 아니다. |

WebRTC 때문에 새로 연 외부 포트는 **7882/UDP와 7881/TCP 두 개**다. `50000–60000/UDP` 범위를 추가로 열지 않았다. TURN/TLS 또는 TURN/UDP 서버는 이번 구성에 없으며 443으로 WebRTC 미디어를 중계하는 TURN 경로도 없다. [LiveKit 공식 포트 설명](https://docs.livekit.io/transport/self-hosting/ports-firewall/)

### 해당 포트가 막힌 Wi-Fi

- **처음 통화를 연결할 때:** UDP가 안 되면 ICE/TCP를 사용할 수 있다. 둘 다 실패하여 LiveKit SDK가 연결 실패를 반환하면, `begin()`이 RTC 후보를 닫고 `/live`를 `rtc=1` 없이 연결한다. 서버도 해당 RTC 브리지를 닫고 **기존 HTTPS/WebSocket PCM 전송 경로**로 보낸다. 이 경로의 재생기는 이전 21:50 버전으로 되돌아가는 것이 아니라 이번에 개선한 AudioWorklet·Worker 구현이다.
- **통화 도중 차단된 망으로 이동할 때:** SDK의 연결 끊김/미디어 재연결/트랙 종료 이벤트, 또는 RTP 패킷 수신이 4초간 늘지 않는 상태를 감지하면 같은 제어 WebSocket에 `audio_transport: pcm`을 보낸다. 처음부터 미디어가 없으면 8초 감지 유예를 쓴다. 수신 패킷 수를 보므로 브라우저가 만든 손실 보정 샘플을 정상 수신으로 오인하지 않는다. 제어 WebSocket 자체도 끊기면 PCM 모드로 다시 연결하며 DB의 통화 ID를 이어 쓴다.
- 서버는 하나의 출력 큐에서 전환 ACK → 아직 중계 대기 중인 PCM → 이후 PCM 순서로 전달한다. 중복 요청은 재생 큐를 초기화하거나 전환 횟수를 늘리지 않는다. 마이크와 Google 연결은 미디어 전환 때문에 재시작하지 않는다. 이미 네트워크로 보낸 손실 구간을 완벽히 복구하는 기능은 아니며, 감지·전송·재생 버퍼 확보 시간 동안 잠시 소리가 멎을 수 있다.
- 한 번 PCM으로 전환하면 **그 통화가 끝날 때까지 PCM을 유지**한다. 연결이 불안정할 때 두 방식 사이를 오가지 않으며, 늦게 끝난 RTC 연결 요청도 PCM을 덮어쓰지 못한다. 다음 통화에서는 다시 WebRTC를 우선 시도한다.
- 대체 경로에도 도메인 HTTPS/WebSocket 연결은 필요하다. 해당 경로까지 차단된 Wi-Fi에서는 통화할 수 없다. TCP 지연으로 음성 공급이 늦어지는 현상까지 대체 경로가 없애 주지는 않는다.

검증 결과:

- `test_fallback.cjs`, `test_rtc_watchdog.cjs`, `test_midcall.py`, `test_transport.cjs`: 초기 실패, 미디어만 막힘, 제어 연결까지 끊김, 중복 ACK, 남은 문장 샘플/순서 보존, 마이크 지속, 같은 통화 ID, RTC 재부착 차단을 검사했다.
- 싱가포르 운영 앱과 Chrome에서 활성 시험 통화를 확인한 뒤 SFU 외부 7882/UDP·7881/TCP 송신을 20초 차단했다. **6.1초 이내** PCM 전환, 같은 통화 ID, 전환 1회, Google 재접속 0회를 확인했다. 시험 규칙은 `finally`에서 제거했고 이후 규칙 목록도 확인했다.
- 전환 후 실제 Google 응답 **8.88초**, 이어 제어 WebSocket 종료·자동 재연결 후 **8.67초**, 합계 **17.55초**를 AudioWorklet으로 재생했다. 이 두 응답에서 버퍼 고갈·삽입 무음은 모두 0이었다. 물리적인 청취 평가나 실제 iPhone/Safari의 Wi-Fi 이동 시험은 수행하지 않았다.
- WebRTC 원음→Opus→실제 수신 시험은 400ms 지터 주입에도 중계 버퍼 고갈 0회였다. 기존 통화/기억 경계 34개, 기록 리포트 102개 검사도 통과했다.

감지 API 근거: [LiveKit RoomEvent](https://docs.livekit.io/reference/client-sdk-js/enums/RoomEvent.html), [수신 RTP 패킷 수](https://developer.mozilla.org/en-US/docs/Web/API/RTCInboundRtpStreamStats/packetsReceived). 감지 임계값과 전환 정책은 이 앱의 구현 선택이다.

## 통화 세션 스프레드시트와 5분 갱신

기존 기록 시트에 `통화 세션` 탭을 추가했다. 연결된 계정의 통화 ID당 한 줄이며, 시작·종료 한국 시각, 상태, 서버 연결 구간 시간 합계, 구간 수, 첫/마지막 전송 방식, 자동 전환 수, 마지막 연결 사유, 기억 정리 상태를 기록한다. 이 세션 탭에는 통화 원문·카드·기억 내용·로그인 이메일을 내보내지 않는다. 시간은 Google 청구 시간이 아니다. 오래된 행의 전송 방식은 새 기록이 없으면 `이전 기록 없음`으로 표시한다.

`003_transport_reporting.sql`은 전송 이벤트와 메타데이터 전용 `call.session_report` 뷰를 추가한다. `marong` 보고 역할에는 이 뷰의 읽기 권한만 추가했다. 전송 이벤트의 `(connection_id, mode)` 제약으로 재시도가 중복 집계되지 않는다. 삭제 표시된 통화는 보고서에서 빠진다. 음성 쓰기 큐에서 DB나 Sheets 업로드를 기다리지 않는다.

이후 2026-11-13 사용자가 통화 전사를 기존 `대화` 탭에 넣고 화자별 배경색을 지정하도록 요청했다. `004_transcript_reporting.sql`의 읽기 전용 `call.transcript_report` 뷰로 저장된 전사를 내보낸다. 삭제된 통화, 제외된 발화, 빈 글은 빠지며 로그인 식별자와 내부 키는 노출하지 않는다. 보고 역할에 원본 `call.turns` 직접 접근이나 쓰기 권한은 주지 않는다. 마이그레이션은 2초 잠금 제한과 15초 실행 제한을 두고 기존 데이터를 변경하지 않는다.

`대화`에서는 `V<발화 ID>`로 카톡 번호와 구분하며 두 출처를 시각순으로 합친다. 전사 중인 글은 같은 행의 내용이 다음 갱신에 바뀌고 중복 추가되지 않는다. 현경은 `#fff2cc`(노랑), 마롱이는 `#e8f0fe`(파랑), 동희는 `#d9ead3`(초록)이며 나머지는 기존 분홍이다. 화자 판정은 저장된 친구 연결·이름을 사용한다. 로그인 계정의 통화 사용자 연결은 변경하지 않으므로 현재 현경으로 연결된 계정의 발화는 현경으로 표시한다. 보고서에는 실제 청취 여부·토큰·참고 기억 수를 추정해서 적지 않는다.

이번 전사·색상 변경은 `/opt/marong/tools/report.py`와 보고용 뷰만 적용한다. 음성·RTC·기억 정리·카톡 서비스와 목소리 설정은 변경하거나 재시작하지 않는다. 분리된 DB에서 `tests/test_report.py`의 102개 검사, `tools/vertex_live/test_transcript_report.py`의 15개 검사, 기존 세션 보고 검사를 통과했다. 보고서만 되돌릴 때는 서버 `/home/opc/marong-report-backups/`의 해당 배포 `report.py`를 복구하면 된다. 추가 뷰는 이전 보고서와 호환된다.

운영 확인: 2026-11-13 01:11:33 KST 자동 갱신 후 `대화`의 1,911행 중 통화 55행이 DB 보고 뷰의 발화 ID 집합과 정확히 일치하고 중복이 없었다. 세 화자의 대표 행은 15칸 전체에 지정 색상이 적용됐다. Apps Script는 기존 `marong2` 배포 주소에서 버전 4로 갱신됐다. 음성·RTC·기억 정리·카톡 4개 서비스의 PID와 시작 시각은 작업 전후 같았다. 원본 통화 표 직접 읽기와 보고 뷰 쓰기 권한도 계속 거부된다.

2026-11-13 사용자 요청으로 `marong-sheet.timer`를 **OnUnitActiveSec=5min, AccuracySec=1s**로 변경했다. 수동 메뉴 요청을 받는 1분 타이머는 유지한다. 전체 보고서는 같은 스냅샷으로 덮어쓰며 일시적인 429/5xx/연결 오류는 2초 뒤 한 번 재시도한다. 운영 첫 전송의 HTTP 500은 재전송으로 회복했고 실제 시트 행·서식·종료 상태를 확인했다. 탭 추가 자체는 기존 Apps Script가 처리했다. 이후 색상 검증에서 서버가 쓰는 배포 `marong2`가 색상 처리가 없는 버전 1에 묶여 있음을 확인하여, 같은 주소·권한의 새 버전에 저장소 `tools/sheet.gs`를 적용했다. 다른 배포 주소나 인증 파일은 변경하지 않는다.

배포 전 백업은 서버의 `latest-failover-backup` 포인터가 가리키는 디렉터리에 있다. 음성 앱 롤백은 통화가 없을 때 이전 `app`을 복구하고 음성 서비스만 재시작한다. 보고서/타이머 롤백은 같은 백업의 `report.py`, `marong-sheet.timer`, `marong-sheet.service`를 복구하고 daemon-reload 한다. 추가 DB 테이블·뷰는 그대로 남겨도 이전 코드와 호환되며 삭제하지 않는다. 인증 파일과 DB 백업은 다른 기기로 옮기지 않는다.

## 자동 정리기와 DB 재시작

확인일: **2026-11-15, 한국 시간**.

2026-11-14 15:36:52 KST에 서버의 무인 업데이트(`apt-daily-upgrade`)가 PostgreSQL을 다시 시작했다. 통화 서비스, Discord 봇, 시트 보고는 연결 풀이나 매번 새 연결을 써서 스스로 회복했다. 자동 정리기(`marong-voice-memory.service`)는 LangGraph 체크포인트에 프로세스 내내 연결 하나를 썼고, 이 연결은 끊긴 뒤 다시 열리지 않았다. 그 뒤 끝난 통화 2건의 정리가 처음에는 `AdminShutdown`, 이어서 `OperationalError`로 세 번 모두 실패했다(`organize_status='failed'`, `organize_attempts=3`). 통화 전사와 시트 기록에는 영향이 없었고, 통화 카드와 기억만 만들어지지 않았다.

- 복구: 2026-11-15 09:19 KST에 진행 중인 통화와 정리가 없는 것을 확인하고 정리기만 다시 시작한 뒤 두 통화를 다시 대기열에 넣었다. 두 통화 모두 첫 시도에 `done`이 됐고 카드와 기억이 생겼다.
- 수정: 정리기는 체크포인트에도 연결 풀(`checkpoint_pool`)을 쓴다. 풀은 연결을 쓰기 전에 확인하고, 서버가 닫은 연결은 새 연결로 바꾼다. `test_organizer_reconnect.py`는 같은 사건(서버가 세션을 끝냄)에서 이전 방식은 다음 작업마다 실패하고 새 방식은 바로 회복하는 것을 함께 확인한다. 버려도 되는 로컬 PostgreSQL 16에서 실제 `pg_ctl restart -m fast` 뒤 정리기 `main()` 루프도 확인했다. 이전 코드는 재시작 뒤 통화의 정리가 실패했고, 새 코드는 첫 시도에 정리했다.
- 같은 일이 다시 생기면: 세 번 실패한 통화는 자동으로 다시 시도하지 않는다. 정리기 로그(`journalctl _SYSTEMD_USER_UNIT=marong-voice-memory.service`)에서 실패 원인이 연결 문제였는지 보고, 정리기가 정상인지 확인한 뒤 해당 통화만 다시 넣는다. 다시 정리하면 Gemini 요청이 통화마다 한 번 더 나간다.

```sql
-- marong_call 역할로, 다시 정리할 통화 ID만 넣는다
UPDATE call.calls SET organize_status='pending', organize_attempts=0, organize_next_at=now(), organize_lease_until=NULL
WHERE deleted_at IS NULL AND status='ended' AND organize_status='failed' AND id IN ('<통화 ID>');
```

## 서버 변경 파일과 재현 자료

`deploy/`에는 실제 운영 설정을 바탕으로 비밀값을 제외한 템플릿을 두었다. 그대로 설치하는 자동 배포 스크립트는 아니며, 기존 Cloudflare Access 설정은 유지해야 한다.

| 자료 | 적용 위치·역할 |
|---|---|
| `marong-rtc.service` | `opc` 사용자 systemd 서비스. 같은 서버의 LiveKit 1.13.11 바이너리 실행. |
| `marong-voice-memory.service` | `opc` 사용자 systemd 서비스. 독립 자동 정리기 실행. |
| `vertex-memory.conf` | 기존 `marong-vertex-live.service` drop-in. 새 venv와 DB 연결 사용. |
| `kakao-voice-memory.conf` | 시스템 `marong.service` drop-in. 자동 문맥 주입과 비공개 자료 보호 활성화. |
| `livekit.example.yaml` | 포트·루프백·방 정리·로그 설정. 실제 키·서버 IP는 서버에서 채운다. |
| `../../marong/call/migrations/002_vertex_memory.sql` | 기존 `marong/call/schema.sql` 다음에 적용한 DB 마이그레이션. |

실제 LiveKit의 `livekit.yaml`과 앱이 읽는 `livekit.json`의 `api_key`/`api_secret`은 서버 안에서 생성하여 서로 일치시킨다. 두 파일 모두 서버 밖으로 복사하지 않으며 Git에는 넣지 않는다. `livekit.json`의 구조만 표시하면 `{"api_key":"서버에서 생성한 값","api_secret":"서버에서 생성한 값"}`이다.

운영 PostgreSQL의 추가 로컬 인증 규칙은 `pg_hba.conf`의 `local marong marong_call peer map=marong_voice`, `pg_ident.conf`의 `marong_voice opc marong_call`이다. 원격 DB 포트나 DB 비밀번호 파일을 추가하지 않았다. 테스트 DB의 별도 규칙과 운영 규칙을 혼동하지 않는다.

서버에만 남기는 항목: Google 키, LiveKit 비밀키, Cloudflare 인증 정보·허용 계정 목록, SSH 인증 파일, 카톡 데이터·DB 덤프. DB·코드 백업은 `/home/opc/marong-voice-backups/`에 유지한다. 비공개 통화 파생 자료가 생긴 뒤에는 카톡 보호 코드를 이전 버전으로 되돌리지 않는다.

## 통화 기억 배포 검증

BUG-118~122 후속 반영은 리뷰와 병합 뒤에 진행한다. 동작 수정은 `85567b1`, BUG-117의 구간 설정 변경은 별도 커밋 `7fe94a4`다. 통화가 없는 시간에 승인 범위의 파일로 아래 순서를 적용한다.

PR #119는 `5f89fd5`로 병합됐다. 런타임 파일 6개로 반영을 시도했으나 2026-11-24 03:47:39 KST에 정리기 유닛 검증이 실패해 운영 파일과 유닛 설정을 복구했다. 운영과 `main`의 `live_session.py` 해시가 다르다. BUG-117은 병합했고, 마롱이 항목 77(2026-11-24 03시대 KST)에 따라 대화 이어 주기 설계에서 컨텍스트 창 압축 값을 정한 뒤 반영한다. 다음 반영의 통화 서버 파일은 승인 범위인 `85567b1`에서 선택한다. [파일별 대조와 QA 결과](../../docs/12-qa/runs/2026-11-24-call-memory-deployment-gate.md)

1. `systemctl --user show marong-vertex-live -p WorkingDirectory --value`로 실제 릴리스의 `tools/vertex_live` 경로를 얻는다. DB와 현재 파일 및 사용자 유닛 설정을 백업하고 해시를 대조한다. 릴리스 루트에 정리기 import에 필요한 동일 버전의 `marong` 패키지가 있는지 확인한다. 되돌리기 스크립트 경로는 반영 전에 기록한다.
2. 병합본의 `call_instruction.md`를 같은 디렉터리의 임시 파일을 거쳐 원자적으로 교체하고 SHA256을 확인한다. 웹 통화 서버는 다음 공급자 연결 때 이 파일을 읽는다. 비활성 디스코드 중계는 계속 정지하고, 중계를 되살릴 때 지시문과 코드 해시를 별도로 확인한다.
3. 웹 통화 릴리스의 코드와 회귀 시험을 확인한 뒤 정리기의 사용자 유닛 drop-in에 `WorkingDirectory`를 1번 경로로, `PYTHONPATH`를 그 릴리스 루트로 둔다. 기존 `ExecStart`를 빈 값으로 초기화한 뒤 기존 로컬 Python으로 그 경로의 `organizer.py`를 실행하도록 설정한다. 기존 인증·DB 설정을 보존한다. 정리기에서 현재 꺼진 친구 기억 작업은 이 반영에서 활성화하지 않는다.
4. 사용자 런타임 경로와 버스 주소를 명시한 환경에서 `systemd-analyze --user verify marong-voice-memory.service`가 기존 유닛을 검증하는지 파일 교체 전에 확인한다. 파일과 drop-in을 설치한 뒤 새 유닛 검증 및 시작 전 import 확인을 거치고, 사용자 유닛을 다시 읽어 재시작한다. PID의 작업 폴더와 실행 파일 SHA256, 서비스 상태, 5분 로그의 오류 수를 확인한다. 자연 발생 통화나 승인된 합성 통화에서 정리 상태를 확인한다. BUG-117을 별도로 반영하면 구간 설정도 확인한다.
5. 되돌리려면 백업한 지시문·코드·유닛 설정을 복원하고, 그 반영에서 추가한 drop-in만 제거한 뒤 사용자 유닛을 다시 읽어 영향받은 서비스를 재시작한다. 카드 숨김과 검침 활성화는 이 절차에 포함하지 않는다.

정리기 drop-in 예시다. `<release>`에 1번에서 확인한 실제 경로를 사용한다.

```ini
[Service]
WorkingDirectory=%h/marong-deploy/<release>/voice-runtime/tools/vertex_live
Environment=PYTHONPATH=%h/marong-deploy/<release>/voice-runtime
ExecStart=
ExecStart=%h/marong-vertex-test/venv-memory2/bin/python organizer.py
```
