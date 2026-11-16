# 통화 엔진 비교 측정

마롱이 통화를 더 싸게 할 수 있는 엔진 조합을 같은 조건에서 재는 도구예요. 지어낸 친구 '지우'가 마롱이에게 거는 10턴짜리 통화 음성을 실제 말하는 속도로 보내고, 엔진마다 다음을 기록해요.

- 친구 말이 끝난 때부터 마롱이 첫 소리가 올 때까지(지연)
- 엔진이 알아들은 친구 말과 글자 오류율(CER)
- 대답 글과 대답 소리(샘플)
- 응답에 담겨 오는 사용량으로 계산한 턴당 비용

클라우드 작업 환경의 프록시는 WebSocket을 지원하지 않아서, 실시간 엔진은 지금 통화가 도는 마롱이 서버(싱가포르)에서 재요. 같은 곳에서 재야 지금 통화와 비교가 정확해요.

## 재는 것

| 이름 | 엔진 | 키 파일(서버 `~/.config/marong-call/`) |
|---|---|---|
| `gemini` | 지금 통화와 같은 Vertex 설정: `gemini-3.8-live`, Sulafat, `ko-KR`, 침묵 700ms, 압축 창 8192/4096 (도구·기억 자료 없음) | `gemini2.key` |
| `openai` | `gpt-realtime-2.1-mini`, marin, 서버 VAD 침묵 700ms | `openai.key` |
| `live` | `gpt-live-1`, noeul | `openai.key` |
| `cascade` | `gpt-live-transcribe`(말이 끝나고 700ms 뒤 확정) → `gpt-6-luna`(추론 없음, 첫 문장이 나오면 바로) → `gemini-3.8-flash-lite-tts` Sulafat와 `gpt-4o-mini-tts` marin을 동시에 | `openai.key`, `gemini.key` |

- 지시문은 운영 통화 지시문 `tools/vertex_live/call_instruction.md`(main 2a473ae)에서 주인 이름만 바꾸고, 지어낸 '지금 상황'과 '기억 자료'를 붙인 `inputs/system_prompt.txt`예요.
- 친구 음성(`inputs/u01~u10`)은 OpenAI `gpt-4o-mini-tts`(coral)로 만든 시험 음성이에요. 다른 받아쓰기 모델로 확인한 CER은 u10만 0.133, 나머지는 0이에요.
- 턴 사이에는 마이크가 계속 무음을 보내고, 대답이 다 '재생'된 뒤 0.6초 있다가 다음 말을 해요.
- 비용 상한은 한 번 돌릴 때 1.5달러(`VB_MAX_USD`)예요. 10턴씩 네 가지면 추정 0.3달러 안팎이에요.

## 돌리기(노트북의 Git Bash, 이 저장소 폴더)

```bash
git fetch origin claude/project-thread-p4wjk1
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- start
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- status    # 약 10분 뒤 DONE
git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- collect
```

- `start`는 이 브랜치의 `bench_server.py`와 `inputs/`만 서버의 `~/marong-voice-bench/<시각>/`에 풀고 백그라운드로 돌려요. 파이썬은 서버의 `~/marong-vertex-test/venv-memory2/bin/python`이 있으면 그것(표준 라이브러리만 씀), 없으면 `python3`을 써요.
- `collect`는 결과 묶음을 받아 이 브랜치의 `tools/voice_bench/server-results/<시각>.tar.gz`로 커밋·푸시해요. 노트북 폴더의 작업 트리·현재 브랜치·인덱스는 그대로예요.
- sudo를 쓰지 않고, 운영 서비스·설정·키 파일은 읽기만 해요. 키 값은 출력·저장하지 않아요.

## 서버에서 바로

```bash
python3 -I bench_server.py check     # 키 파일이 있는지(값 없이)와 요금 없는 모델 조회
python3 -I bench_server.py all       # 전부 차례로, 끝나면 results.tar.gz와 results/DONE
python3 -I bench_server.py gemini    # 하나만
```

## 클라우드에서 흐름 시험

`VB_PROXY_KEYS=1`이면 키 대신 자리표시자를 보내요(프록시가 키를 넣는 클라우드 환경용). `VB_OPENAI_WS`, `VB_VERTEX_WS`, `VB_GEMINI_HTTP`로 가짜 서버를 가리키면 네트워크 없이 흐름을 시험할 수 있어요. 2026-11-16에 가짜 실시간 서버와 실제 OpenAI 글·음성 API로 네 가지 모두 Python 3.9와 3.13에서 돌려 봤어요.

## 결과 파일

- `results/check.json`: 파이썬 버전, ffmpeg 유무, 키 파일 유무(참/거짓), 모델 조회 상태 코드
- `results/s2s-<이름>/turns.jsonl`, `summary.json`, `u01.wav(.mp3)`…: 턴별 지연·CER·대답·비용, 세션 요약, 대답 소리
- `results/cascade/turns.jsonl`: 받아쓰기 확정 시간, 글 모델 첫 글자·첫 문장 시간, 음성별 첫 소리 시간과 지연, 비용
- `results/run-meta.json`: 시작·끝 시각, 엔진별 성공 여부, 쓴 돈 추정

이 브랜치는 측정용이에요. `server-results/`의 결과 묶음은 main에 합치지 않아요.
