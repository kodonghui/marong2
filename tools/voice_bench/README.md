# 통화 엔진 비교 측정

마롱이 통화를 더 싸게 할 수 있는 엔진 조합을 같은 조건에서 측정하는 도구예요. 지어낸 친구 '지우'가 마롱이에게 거는 10턴짜리 통화 음성을 실제 말하는 속도로 보내고, 엔진마다 다음을 기록해요.

- 친구 말이 끝난 때부터 마롱이 첫 소리가 올 때까지(지연)
- 엔진이 알아들은 친구 말과 글자 오류율(CER)
- 대답 글과 대답 소리(샘플)
- 응답에 담겨 오는 사용량으로 계산한 턴당 비용

클라우드 작업 환경의 프록시는 WebSocket을 지원하지 않아서, 실시간 엔진은 지금 통화가 도는 마롱이 서버(싱가포르)에서 재요. 같은 곳에서 재야 지금 통화와 비교가 정확해요.

## 측정하는 것

| 이름 | 엔진 | 키 파일(서버 `~/.config/marong-call/`) |
|---|---|---|
| `gemini` | 지금 통화와 같은 Vertex 설정: `gemini-3.8-live`, Sulafat, `ko-KR`, 침묵 700ms, 압축 창 8192/4096 (도구·기억 자료 없음) | `gemini2.key` |
| `openai` | `gpt-realtime-2.1-mini`, marin, 서버 VAD 침묵 700ms | `openai.key` |
| `live` | `gpt-live-1`, noeul | `openai.key` |
| `cascade` | `gpt-live-transcribe`(말이 끝나고 700ms 뒤 확정) → `gpt-6-luna`(추론 없음, 첫 문장이 나오면 바로) → 목소리 셋을 동시에: `gpt-4o-mini-tts` marin, `gemini-3.8-flash-lite-tts` Sulafat(Vertex global), ElevenLabs `eleven_flash_v2_5` Han Aim | `openai.key`, `gemini2.key`, `elevenlabs.key` |
| `cascade-aai` | AssemblyAI 실시간 받아쓰기 `assemblyai-stt-3-7-realtime-agent`(모델이 말 끝을 정함, `mode=min_latency`, `language_codes=["ko"]`) → 나머지는 `cascade`와 같음 | 위 + `assemblyai.key` |
| `eleven-rt` | ElevenLabs Eleven Realtime v1 Mini(`eleven_realtime_v1_mini`, 받아쓰기·말 끝 판정·글 모델·목소리를 ElevenLabs가 하나의 시스템으로 맞춘 speech-to-speech 모델), 목소리 Han Aim(안 받으면 기본 목소리로 바꾸고 적음), `semantic_vad` eagerness `medium`, 언어 `ko` | `elevenlabs.key` |
| `eleven-agent` | ElevenAgents Custom 모드: Scribe 실시간 받아쓰기 + 말 끝 판정 모델 `turn_v3`(eagerness `normal`) + `gpt-6-luna`(추론 없음) + `eleven_flash_v2_5` Han Aim, 모두 ElevenLabs 안에서. 돌릴 때 `voice-bench` 태그를 단 비공개 에이전트를 하나 만들고(남겨 둠), 서명된 URL로 접속 | `elevenlabs.key`(에이전트 권한 필요) |

- 지시문은 운영 통화 지시문 `tools/vertex_live/call_instruction.md`(main 2a473ae)에서 주인 이름만 바꾸고, 지어낸 '지금 상황'과 '기억 자료'를 붙인 `inputs/system_prompt.txt`예요.
- 친구 음성(`inputs/u01~u10`)은 OpenAI `gpt-4o-mini-tts`(coral)로 만든 시험 음성이에요. 다른 받아쓰기 모델로 확인한 CER은 u10만 0.133, 나머지는 0이에요.
- 턴 사이에는 마이크가 계속 무음을 보내고, 대답이 다 '재생'된 뒤 0.6초 있다가 다음 말을 해요.
- 비용 상한은 한 번 돌릴 때 1.5달러(`VB_MAX_USD`)예요. 10턴씩 네 가지면 추정 0.3달러 안팎이에요.

### ElevenLabs 실시간 엔진 (2026-11-17 추가)

- `eleven-rt`: 서버가 키로 `POST https://api.elevenlabs.io/v1/convai/realtime/client_secrets`에서 짧게 쓰는 비밀값을 받고, `wss://api.elevenlabs.io/v1/convai/realtime?model=eleven_realtime_v1_mini`에 그 값으로 접속해요(OpenAI Realtime과 같은 이벤트). 입력은 24kHz PCM만 돼요. 어떤 인증 방식이 됐는지는 `summary.json`의 `connect`에, 목소리를 받았는지는 `mint`·`voice_used`에 적어요. 비밀값은 어디에도 적지 않아요.
- `eleven-agent`: `POST /v1/convai/agents/create`로 에이전트를 만들고 `GET /v1/convai/conversation/get-signed-url`로 받은 주소에 접속해요. 소리는 16kHz PCM을 `user_audio_chunk`로 보내고, `audio` 이벤트로 받아요. 대답 끝은 `agent_response_complete`, 없으면 2.5초 동안 소리가 없을 때로 봐요.
- 요금은 통화 1분에 0.08달러 + 글 모델 사용량이에요(elevenlabs.io/pricing/api, /pricing/agents, 2026-11-17 읽음). 둘 다 끝난 뒤 `GET /v1/convai/conversations/<id>`에서 실제 청구(`cost_fiat_usd`, `charging`)를 읽어 `summary.json`의 `billing`에 남겨요. 대화 글은 합성 시험 글이라 `turns.jsonl`에만 있어요.
- 읽은 문서(2026-11-17): elevenlabs.io/docs의 `eleven-agents/overview.md`, `eleven-agents/customization/realtime-models.md`, `eleven-agents/guides/openai-realtime-compatibility.md`, `eleven-agents/api-reference/conversations/create-client-secret.md`, `eleven-agents/libraries/web-sockets.md`, `eleven-agents/api-reference/eleven-agents/websocket.md`, `eleven-agents/api-reference/agents/create.md`, `overview/models.md`.
- `VB_ELEVEN_RT_MODEL`, `VB_ELEVEN_RT_EAGERNESS`, `VB_ELEVEN_AGENT_LLM`, `VB_ELEVEN_AGENT_EAGERNESS`로 바꿔요.

### 연쇄형 목소리와 받아쓰기 (2026-11-17 추가)

- 목소리는 글 모델의 첫 문장이 나오는 순간 셋을 한꺼번에 요청하고, 각 목소리의 첫 소리 시간(`latency_s`, 친구 말 끝부터)을 따로 적어요. 나머지 문장은 녹음용으로 뒤에 만들어요. 녹음은 `<턴>-openai.wav`, `<턴>-gemini.wav`, `<턴>-elevenlabs.wav`예요.
- `VB_CASCADE_TTS=openai,gemini,elevenlabs`로 켤 목소리를 골라요. 없으면 키 파일이 있는 것만 켜고, 빠진 것은 `summary.json`의 `tts_skipped`에 적어요.
- ElevenLabs: `POST https://api.elevenlabs.io/v1/text-to-speech/8jHHF8rMqMlg8if2mOUe/stream?output_format=pcm_24000`, 헤더 `xi-api-key`, 본문 `text`·`model_id=eleven_flash_v2_5`·`language_code=ko`. 요금은 보낸 글자 1,000자당 0.04달러(elevenlabs.io/pricing/api, 2026-11-16 읽음).
- Gemini TTS: `https://aiplatform.googleapis.com/v1beta1/projects/<운영 프로젝트>/locations/global/publishers/google/models/gemini-3.8-flash-lite-tts:streamGenerateContent?alt=sse`, 운영 통화와 같은 `gemini2.key`, 헤더 `x-goog-api-key`. 앞부분은 `VB_VERTEX_HTTP`로 바꿀 수 있어요. `VB_GEMINI_TTS_VIA=aistudio`면 예전 AI Studio 경로(`gemini.key`)를 써요.
- 목소리 요청은 `VB_TTS_TIMEOUT`(기본 10초) 동안 바이트가 없거나, 연결이 끊기거나, 429·5xx가 오면 소리가 오기 전일 때만 한 번 다시 보내고 `retries`에 남겨요. 첫 소리 시간은 첫 요청부터 세요.
- AssemblyAI: `wss://streaming.assemblyai.com/v3/ws`, 헤더 `Authorization`(키 그대로), 24kHz 16비트 PCM을 50ms씩 바이너리로 보내요. 말 끝은 모델이 정하고(`Turn`의 `end_of_turn: true`), 말이 끝나고 3초 안에 안 오면 `ForceEndpoint`를 보내요. 친구가 말 중간에 쉬어서 끝 판정이 먼저 난 조각은 `stt_finals_before_end`로 세고, 글은 이어 붙여요. 요금은 세션 시간(시간당 0.45달러)이고 `Termination`의 `session_duration_seconds`로 계산해요. `VB_AAI_MODEL`(기본 `assemblyai-stt-3-7-realtime-agent`, 예전 `universal-3-6-pro`도 됨), `VB_AAI_MODE`(기본 `min_latency`)로 바꿔요. 읽은 문서(2026-11-17): assemblyai.com/docs의 `getting-started/models.md`, `streaming/select-the-speech-model.md`, `streaming/turn-detection.md`, `streaming/message-sequence.md`, `streaming/api-spec/streaming-websocket.md`.

## 돌리기(노트북의 Git Bash, 이 저장소 폴더)

```bash
git fetch origin claude/project-thread-p4wjk1
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- start
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- status    # 약 10분 뒤 DONE
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- collect
```

- `start`는 이 브랜치의 `bench_server.py`와 `inputs/`만 서버의 `~/marong-voice-bench/<시각>/`에 풀고 백그라운드로 돌려요. 파이썬은 서버의 `~/marong-vertex-test/venv-memory2/bin/python`이 있으면 그것(표준 라이브러리만 씀), 없으면 `python3`을 써요.
- `collect`는 결과 압축 파일을 받아 이 브랜치의 `tools/voice_bench/server-results/<시각>.tar.gz`로 커밋·푸시해요. 노트북 폴더의 작업 트리·현재 브랜치·인덱스는 그대로예요.
- sudo를 쓰지 않고, 운영 서비스·설정·키 파일은 읽기만 해요. 키 값은 출력·저장하지 않아요.

## 서버에서 바로

```bash
python3 -I bench_server.py check     # 키 파일이 있는지(값 없이)와 요금 없는 모델 조회
python3 -I bench_server.py all       # 전부 차례로, 끝나면 results.tar.gz와 results/DONE
python3 -I bench_server.py gemini    # 하나만
python3 -I bench_server.py gemini,cascade,cascade-aai   # 여러 개를 차례로(시작 전에 check도 해요)
```

## 클라우드에서 흐름 시험

`VB_PROXY_KEYS=1`이면 키 대신 자리표시자를 보내요(프록시가 키를 넣는 클라우드 환경용). `VB_OPENAI_WS`, `VB_VERTEX_WS`, `VB_GEMINI_HTTP`로 가짜 서버를 가리키면 네트워크 없이 흐름을 시험할 수 있어요. 2026-11-16에 가짜 실시간 서버와 실제 OpenAI 글·음성 API로 네 가지 모두 Python 3.9와 3.13에서 돌려 봤어요.

## 결과 파일

- `results/check.json`: 파이썬 버전, ffmpeg 유무, 키 파일 유무(참/거짓), 모델 조회 상태 코드, ElevenLabs Han Aim 목소리 조회, AssemblyAI 키 확인, Vertex Gemini TTS 한 문장
- `results/s2s-<이름>/turns.jsonl`, `summary.json`, `u01.wav(.mp3)`…: 턴별 지연·CER·대답·비용, 세션 요약, 대답 소리
- `results/cascade/turns.jsonl`, `results/cascade-aai/turns.jsonl`: 받아쓰기 확정 시간, 글 모델 첫 글자·첫 문장 시간, 목소리별 첫 소리 시간과 지연, 비용
- `results/run-meta.json`: 시작·끝 시각, 엔진별 성공 여부, 쓴 돈 추정

이 브랜치는 측정용이에요. `server-results/`의 결과 압축 파일은 main에 합치지 않아요.
