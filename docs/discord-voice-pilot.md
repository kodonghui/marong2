# 마롱이 디스코드 통화 시험

각자의 Discord 서버에 있는 비공개 음성 채널을 기존 마롱이 DM에 연결한다. DM의 고정 메시지에서 `음성 채널 참가하기`를 누르면 Discord에서 음성방이 열린다. 해당 사용자가 입장하면 마롱이가 참가하고, 퇴장하면 연결을 닫는다. 방에 다른 참가자가 있거나 검증된 계정이 없으면 음성 연결을 열지 않는다.

## 적용 범위

- TASK-001 ← SPEC-032~034, API-013~014. 같은 Discord 봇의 음성 전용 Gateway를 추가했다. 암호화된 Discord Opus 수신과 송신에 `@discordjs/voice 0.19.2`를 쓴다.
- TASK-002 ← SPEC-035~037, API-013~015. 전용 UID가 접근하는 Unix 소켓의 `/live`와 `/end`로 싱가포르 서버의 기존 Vertex Live 코드를 실행한다. 한국어 `ko-KR`와 목소리 `Sulafat`를 쓴다. 운영 브라우저의 음성 연결과는 별도 프로세스다.
- TASK-003 ← SPEC-038~039. `006_discord_shared_callers.sql`은 Discord DM과 웹을 같은 사람의 caller에 연결한다. Discord 릴레이는 `MARONG_DISCORD_VOICE_ROOMS`의 사용자·서버·음성방 조합과 DB 연결이 모두 맞아야 통화를 시작한다. 웹과 Discord가 같은 caller로 새 연결을 동시에 열면 먼저 시작한 통화가 유지된다. 반대쪽 연결이 이미 끊긴 경우 그 기록을 닫고 새 통화를 시작한다.
- TASK-004 ← SPEC-039~040. `call.calls.entrypoint`와 `call.transport_events.mode`에 Discord를 기록한다. 연구용 시트는 5분 타이머에서 기존 발화 ID와 색상 규칙으로 표시한다. Discord 재접속은 웹 전송 전환 수에 포함되지 않는다.

## 점검과 운영

- `tests/test_discord_voice_relay.py`는 두 계정의 방과 기억을 확인한다. 웹이 열린 상태에서 Discord를 시작하는 경우, Discord가 열린 상태에서 웹에서 시작하거나 종료하는 경우, PCM 입출력과 기존 통화·전사 보고를 검사한다. Node Opus 변환과 웹의 음성 전환은 각자의 기존 테스트로 확인한다.
- 실제 Discord DAVE 접속, 마이크 입력, 모델 응답과 기기에서의 청취 결과는 각각 확인한다. Gateway가 준비됐다는 로그만으로 왕복 통화를 판정하지 않는다.
- 배포할 때 기존 웹 통화와 Discord 통화가 없는지 먼저 확인하고, 공통 통화 코드와 `006_discord_shared_callers.sql`을 함께 적용한다. 두 음성 서비스와 웹 릴레이를 재시작한 뒤 Gateway의 준비된 방 수와 웹 `/healthz`를 확인한다. Discord 음성을 잠시 내릴 때는 `marong-discord-voice.service`와 `marong-discord-voice-relay.service`를 함께 중지한다.

설계 및 후속 검증 기준은 [디스코드 음성 통화 설계](discord-voice-design.md)에 있다.
