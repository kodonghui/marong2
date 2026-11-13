# 마롱이 디스코드 통화 시험

2026-11-13 KST 기준으로 동희님의 기존 Discord 계정에 비공개 음성 채널을 연결했다. 입장하면 마롱이가 참가한다. Discord에서 마이크를 허용하고 마롱이에게 한국어로 말을 걸면 된다. 방에 다른 참가자가 있거나 검증된 계정이 없으면 음성 연결을 열지 않는다.

## 적용 범위

- TASK-001 ← SPEC-032~034, API-013~014. 같은 Discord 봇의 음성 전용 Gateway를 추가했다. 암호화된 Discord Opus 수신과 송신에 `@discordjs/voice 0.19.2`를 쓴다.
- TASK-002 ← SPEC-035~037, API-013~015. 전용 UID가 접근하는 Unix 소켓의 `/live`와 `/end`로 싱가포르 서버의 기존 Vertex Live 코드를 실행한다. 한국어 `ko-KR`와 목소리 `Sulafat`를 쓴다. 운영 브라우저의 음성 연결과는 별도 프로세스다.
- TASK-003 ← SPEC-038~039. `005_discord_voice.sql`의 뷰로 Discord DM에 연결된 계정의 전용 caller를 찾는다. 웹 로그인 별칭이 있는 caller는 이 시험에서 제외한다. 기존 설계의 웹·Discord 간 임대 테이블은 같은 caller에 두 경로를 열 때 적용한다. 음성 연결은 동희님만 허용하며 현경님 전화 데이터는 해당 연결의 문맥에 포함하지 않는다.
- TASK-004 ← SPEC-039~040. `call.calls.entrypoint`와 `call.transport_events.mode`에 Discord를 기록한다. 연구용 시트는 5분 타이머에서 기존 발화 ID와 색상 규칙으로 표시한다. Discord 재접속은 웹 전송 전환 수에 포함되지 않는다.

## 점검과 운영

- 합성 시험에서 승인된 계정, 다른 채널 거부, 동시 연결 409, 본인 카톡·Discord DM 문맥, PCM 입출력, 종료, 통화 세션 한 줄과 두 화자의 색을 확인했다. Node Opus 변환과 기존 웹 릴레이·통화 중 전송 전환·Discord DM·시트 회귀 시험도 통과했다.
- 실제 Discord DAVE 접속, 마이크 입력, 모델 응답과 기기에서의 청취 결과는 각각 확인한다. Gateway가 준비됐다는 로그만으로 왕복 통화를 판정하지 않는다.
- 서버가 오류를 겪어 Discord 시험을 내려야 하면 `marong-discord-voice.service`와 `marong-discord-voice-relay.service`만 중지·비활성화한다. 이미 쓴 통화·전사 행과 그 행을 읽는 시트 코드를 보존한다. 통화 사이트와 DM은 각자의 기존 서비스에서 운영한다.

설계 및 후속 검증 기준은 [디스코드 음성 통화 설계](discord-voice-design.md)에 있다.
