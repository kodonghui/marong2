# 통화 연결 속도와 무음 고치기: 기능 명세

상태: 초안(2026-11-21 16시대 KST, Claude, corthex 0.12.x). 명세 동결 전이에요.
입력: [요구사항](../02-prd/call-connect.md) REQ-491\~497, [사용자 흐름](../03-user-flow/FL-180-ring-answer-fast.md) FL-180·[FL-181](../03-user-flow/FL-181-call-no-sound.md), [12 QA 고장 기록](../12-qa/call-connect.md) BUG-108\~110, 지금 코드 `main` `ad9f2f4`(`tools/vertex_live/`, `apps/android/`).
뒤 단계: 05 표는 [`marong/call/migrations/010_call_connect.sql`](../../marong/call/migrations/010_call_connect.sql), 06 계약은 [`api/call-live.openapi.yaml`](../../api/call-live.openapi.yaml) 0.2.0-draft(API-107의 새 메시지, API-246), 08 화면 상태는 [08-screens/call-connect.md](../08-screens/call-connect.md)가 이 SPEC 번호를 따라가요.

## 1. 모든 행에 공통인 규칙

- 어디서 도나: SPEC-400·401·402·404는 통화 서버 `tools/vertex_live/`(서버 `server.py`·`live_session.py`·`call_memory.py`, 화면 `static/`)예요. 화면은 서버가 내려주는 파일이라 앱 업데이트 없이 바뀌어요. SPEC-403만 앱(`apps/android/`, 0.3.1)이에요 [사실: 코드 읽음 2026-11-21].
- 섞여 도는 버전: 앱 0.3.0은 새 화면을 그대로 받아요. SPEC-403이 없는 앱에서는 받기 시각 대신 페이지 시작 시각을 기준으로 재요(3.1). 새 화면이 옛 서버를 만나면 모르는 메시지는 서버가 버리고, 옛 화면이 새 서버를 만나면 붙잡기(`hold`)를 보내지 않아 지금처럼 바로 첫마디가 나가요.
- 시각: 저장은 UTC, 보고와 화면은 한국 시각이에요. 시각 기록의 값은 기준점에서 지난 밀리초(정수)예요.
- 대화 글 없음: 시각 기록·재생 진단·로그에는 숫자, 상태 이름, 장치 종류만 남겨요. 대화 글, 이름, 주소, 토큰, 기기 id는 넣지 않아요(REQ-492, AGENTS.md).
- 확실도 표시: [사실] 코드나 문서에서 확인, [추정] 근거 있는 짐작, [확인 필요] 실제 폰에서 봐야 함.

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-400 | 단계 시각 기록과 실제 준비 시각 | REQ-492, REQ-497, FL-180, BUG-108, BUG-110 | `/live` 연결 하나(구간 하나) | ① 화면이 3.1의 표시를 모아, 첫 소리 재생(SPEC-404의 '재생 확인됨')이 처음 확인된 때, 15초가 지났을 때, 연결이 닫힐 때 가운데 가장 이른 때에 `timing` 메시지를 한 번 보내요. ② 서버는 3.1의 서버 표시를 더해 그 구간 줄의 `connect_timing`에 저장해요. ③ 구간 줄은 `state='opening'`, `provider_ready_at` 비움으로 넣고, Gemini의 `setupComplete`를 받으면 `state='open'`, `provider_ready_at=clock_timestamp()`로 바꿔요. ④ 새 통화(이어 받은 통화가 아님)의 첫 구간 종류는 `start`, 이어 받은 통화의 다시 연결은 `reconnect`, 글로 갈아타기는 지금처럼 `handoff`예요 | 메시지가 4KB 넘음 → 전체를 버리고 로그 `timing_rejected reason=size`<br>모르는 칸이나 틀린 값(정수가 아님, 0 미만, 600,000 넘음) → 그 칸만 버림<br>`timing`이 두 번 옴 → 첫 것만 씀<br>Gemini 연결 실패 → 구간을 `start_failed`로 닫음(`provider_ready_at`은 비어 있음)<br>저장 실패 → 로그 `timing_save_failed`, 통화는 그대로 | Given 새 통화, When Gemini가 1.5초 뒤 준비를 알림, Then 첫 구간 `mode='start'`, `provider_ready_at − opened_at ≥ 1.5초`, `connect_timing.server.providerReady ≥ 1500`(TC-570·572)<br>Given 틀린 칸이 섞인 `timing`, Then 맞는 칸만 남고 통화가 이어짐(TC-571) | active |
| SPEC-401 | 정적 파일 캐시와 스크립트 순서 | REQ-495, FL-180, BUG-108 | 통화 화면(`/`)을 엶 | ① 서버가 시작할 때 정적 파일(3.2 목록)마다 내용 SHA-256의 앞 12자리를 버전으로 셈해요. ② `index.html`을 내려줄 때 그 파일들의 주소에 `?v=<버전>`을 붙이고, 화면 코드가 쓰는 워크릿·대기음 주소도 같은 버전 표(`data-assets`)로 넘겨요. ③ 주소의 버전이 지금 파일 버전과 같은 정적 파일만 `Cache-Control: private, max-age=31536000, immutable`로 내려주고, 나머지(버전 없음, 버전 틀림, HTML, `/status`, `/api/*`, `/live`, 오류)는 지금처럼 `no-store`예요. ④ `index.html`은 `app.js`를 LiveKit보다 먼저 실행되게 두고(3.2), `livekit-client.js`는 화면이 열리자마자 `async`로 받기 시작하되 기다리지 않아요. WebRTC 연결(SPEC-402 ②)만 그 스크립트를 기다려요. ⑤ 서버가 `index.html`의 `data-theme`를 한국 시각으로 정해 내려줘요(`app.js`와 같은 규칙). CSP가 인라인 스크립트를 막아서 인라인으로 하지 않아요 | 파일을 읽지 못함 → 그 파일은 버전 없이 `no-store`(지금과 같음), 로그 `asset_hash_failed`<br>LiveKit 스크립트를 못 받음 → WebRTC 없이 PCM으로 통화(지금 `rtcEnabled=false`와 같음) | Given LiveKit 응답이 5초 늦음, When 통화 화면을 엶, Then 0.5초 안에 테마와 상태 글이 바뀌고 걸기 버튼이 보임(TC-575)<br>Given 두 번째로 화면을 엶, Then 버전이 같은 정적 파일은 네트워크로 받지 않음(Resource Timing `transferSize=0`)(TC-573·574) | active |
| SPEC-402 | 동시 시작과 첫마디 붙잡기 | REQ-491, FL-180, BUG-108 | 통화 시작(`begin`): 걸기 버튼, 벨 받기(`autoAnswer`), 다시 걸기 | ① 화면은 AudioContext를 만들고 `resume`한 뒤 세 가지를 한꺼번에 시작해요. 가. 재생·녹음 워크릿 올리기와 마이크(`getUserMedia`). 나. WebRTC(`POST /api/rtc` → LiveKit 연결, 제한 12초 그대로). 다. `/live`를 `hold=1`(WebRTC를 쓰면 `rtc=1`도)로 엶. ② 화면은 소리가 나갈 준비가 되면 `audio_ready`를 한 번 보내요. WebRTC 트랙을 받고 오디오 요소 `play()`가 끝났으면 `path:"webrtc"`, WebRTC를 안 쓰거나 실패했고 재생 워크릿이 올라갔으면 `path:"pcm"`이에요. ③ 서버는 `hold=1`인 새 통화에서 첫마디 신호(벨의 '(전화 연결됨)'처럼 마롱이가 먼저 말하게 하는 신호)를 `audio_ready`를 받거나 `ready`를 보낸 뒤 3,000ms가 지날 때까지 붙잡아요. ④ 그때까지 WebRTC 짝이 붙지 않았으면 그 소리는 PCM으로 가요(지금 `self.rtc`가 없을 때와 같음). WebRTC 짝이 뒤에 붙으면 마롱이 소리가 쌓여 있지 않은 턴 사이에서만 넘어가요. ⑤ 화면이 처음 열릴 때 `/status`와 프로필(`/chat/api/profile`)을 동시에 불러요 | 마이크 거절 → 지금처럼 '마이크 사용을 허용해 줘…'로 끝냄(다른 두 분기도 닫음)<br>WebRTC 실패 → PCM으로 이어 감(지금 '실시간 소리 연결을 다시 확인하고 있어.')<br>`audio_ready`가 3,000ms 뒤에 옴 → 이미 보낸 첫마디 신호를 다시 보내지 않음<br>다시 연결(`resume`) → 붙잡지 않음(첫마디 없음) | Given 마이크 1초·LiveKit 3초 늦음, When 벨 받기, Then `/live` 연결 시작이 `begin`에서 0.3초 안이고 세 분기가 겹쳐 돎(TC-576)<br>Given `audio_ready` 없음, Then 첫마디 신호가 3초 뒤 한 번(TC-577)<br>Given LiveKit이 안 붙음, Then 3초 안에 PCM으로 첫마디가 재생되고 한 턴 안에서 두 경로가 섞이지 않음(TC-578)<br>Given 두 요청 각 0.5초, Then 둘이 0.1초 안에 함께 시작(TC-579) | active |
| SPEC-403 | 앱 0.3.1: 다시 불러오지 않는 받기, 벨 때 미리 준비, 출력 장치 | REQ-491, REQ-494, REQ-496, FL-180, FL-181, BUG-108, BUG-109 | 앱 0.3.1(versionCode 9) | ① 받기: 통화 중이 아니고 WebView가 통화 화면(`/`, 같은 출처)을 다 불러온 상태면 `loadUrl` 대신 `evaluateJavascript`로 `window.__marongApp.answerRing(<벨 id>, <받은 시각 epoch ms>)`를 불러요. 그 밖에는 지금처럼 벨 주소를 불러오되, 앱이 꺼져 있었으면 시작 주소를 먼저 부르지 않고 벨 주소만 한 번 불러와요. 받은 시각은 화면이 시각 기록의 기준점으로 써요(3.1). ② 벨이 울릴 때 앱 화면이 살아 있고 통화 중이 아니고 통화 화면이 떠 있으면 `window.__marongApp.prepareCall()`을 한 번 불러요. 화면은 `/status`를 받고 LiveKit 스크립트를 받아 둘 뿐, 마이크·`/api/rtc`·`/live`는 열지 않아요. ③ 통화가 시작되면(`callStarted`) 출력 장치를 유선 헤드셋·헤드폰 → USB 헤드셋 → 블루투스(LE·SCO) → 내장 스피커 순으로 골라 정해요(Android 12 이상 `setCommunicationDevice`, 그 아래는 이어폰이 없을 때 `setSpeakerphoneOn(true)`). 내장 수화부는 고르지 않아요. 통화 중 장치가 붙거나 빠지면 다시 골라요. 통화가 끝나면 앱이 바꾼 것을 되돌려요. ④ 고른 장치, 통화 볼륨(지금 값과 최댓값), 벨소리 모드를 화면에 넘겨 재생 진단(SPEC-404 ④)에 넣어요 | 벨 id가 UUID가 아님 → 아무것도 안 함(지금 `PushState.answerRing` 규칙 그대로)<br>`answerRing`이 없음(옛 화면) → 벨 주소를 불러옴<br>장치 정하기 실패(예외) → 로그 `audio_route_failed`, 통화는 그대로, 진단의 장치는 `unknown`<br>통화 중 다른 앱이 통화 모드를 가져감 → 다시 정하지 않고 진단에 남김 | Given 통화 화면이 열린 앱, When 받기, Then `loadUrl`이 불리지 않고 `answerRing`이 불림. 앱이 꺼져 있었으면 페이지 불러오기는 한 번(TC-584)<br>Given 벨이 울림, Then `prepareCall` 한 번, 마이크·연결 없음(TC-585)<br>Given 유선·USB·블루투스·없음, Then 그 순서로 고르고 수화부는 안 고름(TC-586) | active |
| SPEC-404 | 재생 확인과 PCM으로 바꾸기, 재생 진단 | REQ-493, REQ-494, FL-181, BUG-109 | WebRTC로 통화 중(`rtcClient` 있음) | ① 화면은 500ms마다 봐요. 들어옴 = 받은 트랙의 크기 RMS > 0.008(지금 입 움직임과 같은 값). 재생 증거 = 오디오 요소가 `paused=false`이고, WebRTC 통계 `media-playout`의 `totalSamplesCount`가 지난번보다 늘었음. `media-playout`이 없는 브라우저면 요소 상태와 LiveKit `canPlaybackAudio`만 봐요. ② 들어옴이 있는데 재생 증거가 없으면 먼저 한 번 `element.play()`와 `room.startAudio()`를 다시 불러요. 같은 턴에서 그런 시간이 모두 2,000ms가 되면 지금 PCM 바꾸기(`fallbackToPCM`)를 이유 `rtc_silent`로 불러요. 서버는 이 이유를 소리 경로 기록(`call.transport_events`)에 남겨요. ③ 바꾸는 동안 상태 글 '소리 연결을 바꾸고 있어. 통화는 계속 이어갈게.'(지금 문구)를 첫 PCM 소리가 재생되거나 3초가 지날 때까지 보여요. ④ 화면은 재생 상태가 바뀔 때마다(30초에 한 번까지) `playback` 메시지를 보내고, 서버는 그 구간 줄의 `playback`에 마지막 값을 저장해요(3.3). ⑤ LiveKit `AudioPlaybackStatusChanged`에서 `canPlaybackAudio=false`면 `startAudio()`를 부르고, 실패하면 '화면을 한 번 눌러 줘. 바로 이어질게.'를 보여요 | AudioContext가 `running`이 아님 → PCM으로 바꾸지 않고 지금처럼 '화면을 한 번 눌러 줘. 바로 이어질게.'(PCM도 같은 엔진이라서)<br>마롱이가 말하지 않는 동안 → 재지 않음<br>PCM으로 바꾼 뒤 → 이 확인은 멈추고, PCM 재생 상태(`playbackStats`)만 진단에 넣음<br>알 수 없는 `playback` 값 → 그 칸만 버림 | Given 들어오는 소리는 있고 `play()`가 거절됨, When 마롱이가 말함, Then 2초 안에 PCM으로 바뀌고 `pcm`/`rtc_silent` 기록, 상태 글이 잠깐 보임(TC-580)<br>Given AudioContext `suspended`, Then '화면을 한 번 눌러 줘. 바로 이어질게.', 누르면 소리가 남(TC-581)<br>Given 정상 WebRTC 1분, Then `rtc_silent` 없음(TC-583)<br>Given `playback` 메시지, Then 허용한 칸만 저장(TC-582) | active |

## 3. 자세한 규칙

### 3.1 시각 기록(`timing`)

기준점(0): 앱 0.3.1의 벨 받기는 받기를 누른 시각(SPEC-403 ①), 걸기 버튼은 버튼을 누른 시각이에요. 받은 시각이 없으면(앱 0.3.0, 웹) 페이지 시작(`performance.timeOrigin`)이에요. 이때는 `base:"page"`로 적어요.

| 칸 | 뜻 | 누가 |
| --- | --- | --- |
| `base` | `answer`·`button`·`page` | 화면 |
| `entry` | `ring`·`button`·`redial` | 화면 |
| `reloaded` | 이 통화를 위해 페이지를 새로 불러왔는지(참·거짓) | 화면 |
| `cachedAssets`, `fetchedAssets` | 3.2 목록 가운데 캐시에서 온 파일 수, 네트워크로 받은 파일 수 | 화면(Resource Timing) |
| `pageStart` | 페이지 시작 | 화면 |
| `appStart` | `app.js` 첫 줄 | 화면 |
| `statusReady` | `/status`와 프로필을 받음 | 화면 |
| `micReady` | 마이크와 녹음 워크릿 준비 | 화면 |
| `rtcReady` | LiveKit 연결과 트랙 받음(못 하면 없음) | 화면 |
| `liveOpen` | `/live` 웹소켓 열림 | 화면 |
| `ready` | 서버 `ready` 받음 | 화면 |
| `audioReady` | `audio_ready`를 보냄 | 화면 |
| `firstAudioIn` | 마롱이 소리가 처음 들어옴(RMS > 0.008이나 첫 PCM 조각) | 화면 |
| `firstAudioPlayed` | 첫 재생 확인(SPEC-404 ①의 증거, PCM이면 재생 워크릿의 `playedMs > 0`) | 화면 |
| `server.wsOpen` | 서버가 웹소켓을 받음(서버 표시의 기준 0) | 서버 |
| `server.callRow` | 통화 줄을 만들거나 이어 받음 | 서버 |
| `server.providerReady` | Gemini `setupComplete` | 서버 |
| `server.greetingSent` | 첫마디 신호를 보냄(붙잡기 뒤) | 서버 |
| `server.firstAudioOut` | 마롱이 소리를 처음 내보냄 | 서버 |

- 저장 모양: `{"v":1,"client":{…},"server":{…}}`. 화면 칸은 위 이름만, 값은 0\~600,000 정수(그 밖은 3.1 표의 글자 값)예요.
- REQ-491 측정법: `client.firstAudioPlayed`(기준점이 `answer`인 줄만)의 P95예요. `base:"page"` 줄은 받기 전 시간이 빠진 값이라 REQ-491 판정에 쓰지 않고 참고만 해요.

### 3.2 정적 파일과 순서

- 버전을 붙이는 파일: `app.js`, `style.css`, `capture.js`, `playback.js`, `worker-socket.js`, `transport.js`, `rtc-client.js`, `livekit-client.js`, `wait-tone.wav`(지금 서버가 내려주는 목록과 같음, `server.py`의 정적 파일 목록) [사실]. 얼굴 그림 `/face/v1/`은 지금처럼 따로 1년 캐시예요.
- `index.html`의 스크립트 순서: `worker-socket.js`, `rtc-client.js`, `app.js`는 `defer`로 두고, `livekit-client.js`는 `async`로 따로 둬요. `rtc-client.js`는 LiveKit을 쓰기 전에 `window.LivekitClient`가 생길 때까지 기다려요(제한은 LiveKit 연결 12초 안에 들어감).
- 대기음(`wait-tone.wav`)은 지금처럼 기다리지 않고 받아 둬요.

### 3.3 재생 진단(`playback`)

| 칸 | 값 |
| --- | --- |
| `path` | `webrtc`·`pcm` |
| `element` | `playing`·`paused`·`none` |
| `context` | `running`·`suspended`·`interrupted`·`closed` |
| `playout` | `advancing`·`stalled`·`unsupported` |
| `silentMs` | 이 구간에서 들어옴은 있는데 재생 증거가 없던 시간의 합(0\~600,000) |
| `device` | `speaker`·`wired`·`usb`·`bluetooth`·`earpiece`·`unknown`(앱 0.3.1만, 웹은 `unknown`) |
| `voiceVolume`, `voiceVolumeMax` | 통화 볼륨 지금 값과 최댓값(0\~100, 앱 0.3.1만) |
| `ringer` | `normal`·`vibrate`·`silent`·`unknown` |
| `changes` | 서버가 셈: 이 구간에서 `playback`을 받은 횟수 |

### 3.4 Chromium과 앱의 출력 장치

- Chromium은 통화 모드에서 유선 → USB → 블루투스 → 스피커 순으로 기본 장치를 골라요 [사실: Chromium `CommunicationDeviceSelector` 소스, 2026-11-21 읽음]. 앱이 같은 순서로 다시 정하는 것(SPEC-403 ③)은 WebView가 그렇게 하지 않는 폰을 막는 안전장치예요. 둘이 다투지 않는지는 실제 폰에서 봐요 [확인 필요, TC-588].
- 무음 모드는 통화 모드 소리를 끄지 않는 것이 Android 기본이에요 [추정]. 진단의 `ringer`로 확인해요.

## 4. 경우의 종류

| 경우 | 시각 기록 기준 | 붙잡기 | 재생 확인 |
| --- | --- | --- | --- |
| 앱 0.3.1 벨 받기 | `answer` | 함 | 함 |
| 앱 0.3.0 벨 받기 | `page` | 함 | 함 |
| 걸기 버튼(앱·웹) | `button` | 함(첫마디 신호가 있을 때만) | 함 |
| 다시 연결 | `button`이나 `page` | 안 함 | 함 |
| PCM 통화(WebRTC 꺼짐) | 같음 | 함(`path:"pcm"`) | 안 함(PCM 진단만) |
| 디스코드 음성 | 이 명세 밖 | 이 명세 밖 | 이 명세 밖 |

## 5. 요구사항 없이 생긴 동작

없어요.

## 6. 실제 폰에서 확인할 것

- 앱 WebView에서 `media-playout` 통계가 나오는지 [확인 필요]. 안 나오면 요소 상태와 `canPlaybackAudio`만으로 판단해요(SPEC-404 ①).
- 오디오 요소 재생과 Chromium 통화 모드 출력 장치가 실제로 어디로 가는지(TC-588).
- 받기부터 첫 소리 재생 P95(TC-587, REQ-491).
