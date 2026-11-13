# 마롱이 디스코드 1:1

사용하는 사람은 서버에서 숫자 계정 ID를 확인하고 연결한 두 사람이다. 같은 비공개 디스코드 서버에 들어온 뒤 마롱이 프로필에서 **메시지**를 누른다. 태그나 슬래시 명령 없이 DM에 바로 말을 걸면 된다. 서버 채널이나 그룹 DM은 대화 대상이 아니며, 새로 서버에 들어와도 연결되지 않은 계정에는 답장하지 않는다.

두 사람의 디스코드 DM은 독립이다. 각 계정의 기존 카톡 1:1 대화와 통화 기억만 이어 쓴다. 카톡 단체방 원문과 섞인 과거 요약은 디스코드 문맥에 포함하지 않는다. 기존 마롱이 PostgreSQL에 디스코드 대화가 별도 방으로 추가된다. 새 디스코드 기록은 같은 사람의 카톡 1:1·연결된 통화에도 쓰인다. 디스코드에서 보인 내용은 기존 연구용 시트의 `대화` 탭에 `Discord DM`으로 구분되어 5분마다 반영된다.

선톡은 받는 사람이 동의하면 계속 켜진다. DM을 열기 전에 동의가 등록된 사람은 평소처럼 말을 걸면 선톡 일정이 시작된다. DM에서 **먼저 톡해 줘**라고 말해 켜거나 **선톡 끄기**로 중지할 수 있다. 현경님은 한국 시간 07:00~24:00 하루 최대 36번, 동희님은 12:00~21:00 하루 최대 2번을 사용한다. 시간 구간마다 최대 한 번, 최근 대화 중에는 기다리고 두 번 연속 전달에 실패하면 새 DM을 받을 때까지 쉰다. 연결된 DM에 선톡 일정이 시작되면 기존 카톡 쪽 같은 사람의 일정은 디스코드로 옮겨진다. 디스코드에서 끄더라도 카톡 선톡이 자동으로 재개되지는 않는다.

첫 DM부터 대화에 바로 답한다. 사용법 안내는 **도움말**을 요청하면 나온다. 운영 설정에서 친구별 첫 답장을 지정할 수 있으며, 한 번 전달된 뒤에는 평소처럼 대화한다.

## 운영

- 기존 통화 메모리 마이그레이션을 적용한 `marong` DB에 `010_discord_dm.sql`, `011_discord_proactive_consent.sql`을 순서대로 적용한다. 계정 확인 후에만 DB 관리자 역할로 `tools/link_discord.py <Discord 숫자 ID> <friend_id> <하루 횟수> <시작 시> <끝 시>`를 실행한다.
- 새 봇 토큰은 서버의 root 전용 파일 `/etc/marong-discord/token`에 두고 systemd 자격 증명으로 전달한다. 앱과 비공개 서버 ID는 `/etc/marong-discord/config`의 `MARONG_DISCORD_APP_ID`, `MARONG_DISCORD_GUILD_ID`에 둔다. 코드·시트에는 토큰과 Discord 사용자 ID 원문을 적지 않는다.
- 첫 답장을 지정할 때는 같은 설정 파일의 `MARONG_DISCORD_FIRST_REPLIES`에 `friend_id`를 키로, 문구를 값으로 쓰는 JSON 객체를 넣는다.
- `/opt/marong-discord`에 코드와 `requirements-discord.txt`에 고정된 Discord 의존성을 설치한다. `deploy/marong-discord.service`는 기존 `/opt/marong`의 모델 설정과 DB를 사용한다. 같은 DB의 정리 작업자는 카톡과 병행 중에는 기존 작업자 하나를 쓰고, 카톡을 중지할 때는 Discord 설정에서 `MARONG_DISCORD_MEMORY_WORKER=1`로 옮긴다.
- `deploy/marong-discord-context.conf`는 카톡 서비스의 drop-in이다. 같은 사람의 디스코드 최근 기록을 카톡 1:1에 연결하고 선톡 전환을 적용한다. 전화 서비스와 스프레드시트 타이머는 재시작할 필요가 없다.
- Gateway 연결은 서버에서 Discord로 나가는 연결이다. 기존 통화 주소는 `https://marong.corthex-hq.com/`이며 `marong-vertex-tunnel.service`는 꺼진 상태를 유지한다.
- 점검: `python tests/test_discord_dm.py`(별도 테스트 Postgres, 가짜 Discord·모델), `systemctl status marong-discord.service` 및 본인 계정의 실제 DM. 운영에서 타인의 DM을 열어 점검하지 않는다.
