# 통화 갤럭시 시험

현경님 갤럭시 최신 Chrome에서 통화가 화면 꺼짐·다른 앱에서도 이어지는지 미리 보는 시험이에요([기능 명세 7.1](../../docs/04-functional-spec/spec.md)). 실제 통화 웹앱이 아니라 WebRTC·마이크·화면 켜 두기·쉬는 중 말소리 감지만 있는 한 장짜리 페이지와 작은 서버예요. 서버는 표준 라이브러리만 써요.

## 켜고 끄기(내 컴퓨터의 Git Bash, 이 저장소 폴더)

처음 한 번, 서버에 OpenAI 키를 넣어요. `Paste the OpenAI key and press Enter`가 나오면 키를 붙여 넣고 Enter를 눌러요. 키는 화면에 안 보이고 서버의 내 계정 폴더에만 저장돼요. `saved`가 나오면 된 거예요. 이 한 줄은 PowerShell에서도 돼요. 시험 서버를 켠 뒤에 넣어도 서버가 키 파일을 다시 읽어서 다시 켤 필요가 없어요.

```bash
ssh -t ko-family 'umask 077; mkdir -p $HOME/.config/marong-call; echo Paste the OpenAI key and press Enter; stty -echo; read -r k; stty echo; printf %s $k > $HOME/.config/marong-call/openai.key; test -s $HOME/.config/marong-call/openai.key && echo saved || echo NOT saved'
```

```bash
bash deploy/ovh.sh galaxy-test start    # 시험 주소(https://….trycloudflare.com)가 나와요. 켜져 있으면 끄고 다시 켜요
bash deploy/ovh.sh galaxy-test status   # 켜짐·꺼짐과 주소
bash deploy/ovh.sh galaxy-test stop     # 끄기
```

- `start`는 시험 파일만 서버의 `~/marong-galaxy-test/src`로 올리고, 시험 서버(127.0.0.1)와 Cloudflare 임시 터널을 켜요. sudo를 쓰지 않고 마롱이 카톡 봇·필받음 같은 다른 서비스와 그 터널 설정은 건드리지 않아요.
- 처음 나오는 줄 `{"ok": true, "key": true, "model": "200", …}`에서 `key`는 키 파일이 있는지, `model`은 요금 없는 모델 조회 결과예요(200이면 키가 맞음). 크레딧이 남았는지는 전화를 걸어 봐야 알아요. 크레딧이 없으면 세션이 안 만들어지고(요금 없음) 화면에 그렇게 나와요.
- 포트 8791을 다른 프로그램이 쓰면 `MARONG_TEST_PORT=8792 bash deploy/ovh.sh galaxy-test start`.
- cloudflared는 서버의 PATH, 그다음 `~/.local/bin/cloudflared`에서 찾아요. 없으면 [Cloudflare 공식 GitHub 릴리스](https://github.com/cloudflare/cloudflared/releases)의 `cloudflared-linux-amd64`를 서버의 `~/.local/bin/cloudflared`로 받아 `chmod 755` 하고, `sha256sum` 값이 릴리스에 적힌 값과 같은지 확인해요(sudo 없이). 다른 곳에 두었으면 `CLOUDFLARED=/서버의/절대/경로 bash deploy/ovh.sh galaxy-test start`.
- 이 명령들은 Git Bash에서 실행해요. Windows PowerShell은 `&&`를 몰라요.
- 임시 주소는 로그인 없이 누구나 열 수 있어요. 주소는 시험하는 사람에게만 주고, 시험이 끝나면 `stop` 해요.

## 비용 상한

gpt-live-1은 분당 0.05달러예요(연결된 동안 조용해도 과금). 서버가 스스로 막아요.

| 상한 | 기본 |
|---|---|
| 세션 수 | 16개 |
| 한 세션 길이 | 20분(화면이 19분 30초에 끊고, 서버가 21분에 한 번 더 닫음) |
| 모든 세션을 더한 통화 시간 | 120분(약 6달러). 닿으면 새 세션을 거절하고 열린 세션을 닫아요 |
| 한 번에 열린 세션 | 3개 |
| 서버 수명 | 8시간. 지나면 열린 세션을 닫고 서버와 터널이 꺼져요 |

화면이 끝을 확인하지 못한 세션(끊김 등)은 서버가 sideband(`/attach`)로 `session.close`를 보내 닫아요.

## 가짜 통화

주소 뒤에 `?fake=1`을 붙이면 OpenAI 없이 페이지 안의 가짜 상대(3초마다 삐 소리)와 통화해요. 요금이 없어서 크레딧이 없어도 쉬는 중 말소리(3번), 홈 화면 앱(5번), 화면 켜 두기(6번)와 화면 동작을 볼 수 있어요.

## 시험 순서

페이지의 '시험 순서' 1~7이 명세 7.1의 1~7이에요. 항목마다 '됐어요·안 됐어요·애매해요·메모' 버튼이 있고, 통화 중에는 '잘 들림·안 들림·울림·끊김' 버튼으로 느낀 것을 그때그때 남겨요. 5번의 'Access 뒤 설치'는 실제 주소를 만들 때 봐요. 이 시험에서는 임시 주소에서 설치되는지만 봐요.

## 기록과 결과

- 말 내용은 기록하지 않아요. 시각, 상태, 화면 보임·숨김, 소리 크기, 이벤트 종류와 수, 누른 결과와 메모만 서버의 `~/marong-galaxy-test/run-*.jsonl`(나만 읽기)에 남아요. sideband로 오는 원음 사본과 자막은 읽자마자 버려요.
- 결과는 `시험 주소/report`(표)와 `/report.json`에서 봐요. 신호 간격(15초 기대), 30초 넘게 늦은 신호, 쉬는 중 감지 수(타이머·AudioWorklet), 마롱이 소리 재기, 세션별 닫힌 이유가 나와요.

## 시험(내 컴퓨터)

```bash
python tests/test_galaxy_test.py   # 가짜 OpenAI로: 정적 파일·CSP, 같은 사이트 확인, 세션 요청 모양, 잘못된 요청, 세션·시간 상한, 한도 429 전달, 기록 거르기, 끝내기·결과
```

## 파일

| 파일 | 하는 일 |
|---|---|
| `server.py` | 시험 서버: 페이지, 세션 만들기(`POST /v1/live/sessions`), 신호·끝 받기, 상한, 결과 |
| `run.sh` | 서버에서 시험 서버와 임시 터널 켜기·끄기·상태 |
| `static/app.js` | 통화·쉬기·깨우기, 끊김 뒤 다시 잇기, 화면 켜 두기, 말소리 감지(타이머), 15초 신호, 가짜 통화 |
| `static/worklet.js` | AudioWorklet 말소리 감지 |
| `static/index.html`, `manifest.webmanifest`, `sw.js`, `icon-192.webp` | 화면, 홈 화면 앱 설치 |
