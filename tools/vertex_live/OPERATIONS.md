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

기존 기록 시트에 `통화 세션` 탭을 추가했다. 연결된 계정의 통화 ID당 한 줄이며, 시작·종료 한국 시각, 상태, 서버 연결 구간 시간 합계, 구간 수, 첫/마지막 전송 방식, 자동 전환 수, 마지막 연결 사유, 기억 정리 상태를 기록한다. 통화 원문·카드·기억 내용·로그인 이메일은 내보내지 않는다. 시간은 Google 청구 시간이 아니다. 오래된 행의 전송 방식은 새 기록이 없으면 `이전 기록 없음`으로 표시한다.

`003_transport_reporting.sql`은 전송 이벤트와 메타데이터 전용 `call.session_report` 뷰를 추가한다. `marong` 보고 역할은 뷰만 읽고 통화 원문 접근 권한은 얻지 않는다. 전송 이벤트의 `(connection_id, mode)` 제약으로 재시도가 중복 집계되지 않는다. 삭제 표시된 통화는 보고서에서 빠진다. 음성 쓰기 큐에서 DB나 Sheets 업로드를 기다리지 않는다.

2026-11-13 사용자 요청으로 `marong-sheet.timer`를 **OnUnitActiveSec=5min, AccuracySec=1s**로 변경했다. 수동 메뉴 요청을 받는 1분 타이머는 유지한다. 전체 보고서는 같은 스냅샷으로 덮어쓰며 일시적인 429/5xx/연결 오류는 2초 뒤 한 번 재시도한다. 운영 첫 전송의 HTTP 500은 재전송으로 회복했고 실제 시트 행·서식·종료 상태를 확인했다. Apps Script는 받은 탭을 처리하는 기존 구조를 그대로 사용하므로 웹 앱 재배포는 필요 없다.

배포 전 백업은 서버의 `latest-failover-backup` 포인터가 가리키는 디렉터리에 있다. 음성 앱 롤백은 통화가 없을 때 이전 `app`을 복구하고 음성 서비스만 재시작한다. 보고서/타이머 롤백은 같은 백업의 `report.py`, `marong-sheet.timer`, `marong-sheet.service`를 복구하고 daemon-reload 한다. 추가 DB 테이블·뷰는 그대로 남겨도 이전 코드와 호환되며 삭제하지 않는다. 인증 파일과 DB 백업은 다른 기기로 옮기지 않는다.

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
