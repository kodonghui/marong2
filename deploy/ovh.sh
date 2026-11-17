#!/usr/bin/env bash
# 노트북(맥·리눅스·윈도우 Git Bash)에서 OVH 서버의 마롱이를 다루는 명령. 이 저장소 폴더에서 실행한다.
# 서버는 ssh 설정의 별칭으로 접속한다(기본 ko-family). 다른 별칭이면: MARONG_HOST=별칭 bash deploy/ovh.sh …
#   install      코드를 올리고 설치(Postgres·pgvector·marong 계정·/opt/marong·systemd). 처음 한 번, 코드를 고칠 때마다.
#                마롱이가 켜져 있으면 새 코드로 다시 켬
#   migrate-env  지금 돌던 봇(/opt/kakao-bot/.env)의 BOT_TOKEN·Claude 키를 마롱이 .env 로 옮김(서버 안에서만, 값은 안 보임)
#   env          서버의 /opt/marong/.env 를 nano 로 엶(직접 값 넣기. 저장: Ctrl+O, 나가기: Ctrl+X)
#   check        점검(설정·Claude 키·Postgres·임베딩·요약·공인 IP). 처음엔 임베딩 모델을 내려받느라 몇 분 걸림
#   switch       점검이 통과하면 옛 봇(kakao-bot)을 끄고 마롱이를 켬(같은 봇 토큰을 두 곳에서 켜지 않게)
#   rollback     마롱이를 끄고 옛 봇(kakao-bot)을 다시 켬
#   restart      마롱이 다시 켜기 / stop  마롱이 끄기 / status  상태 보기
#   logs         로그 보기(Ctrl+C 로 나옴)
#   prompt       prompt.md·welcome.txt·knowledge/ 만 올림. 재시작 없이 다음 메시지부터 반영
#   admin …      기록 보기: admin friends | people | rooms | show <이름 또는 #키> [개수] | stats
#                친구 고치기: admin link <#키> <친구> | unlink <#키> | share <친구> on|off
#                           | friendship <친구> <친구> <관계> [close] (close: 가까운 사이라 근황까지. 기록은 안 지움)
#                선톡 일정: admin schedule <친구> <하루 횟수> [시작-끝 시] | schedule <친구> default
#                           | schedule <친구> off|on (선톡 끄기·다시 켜기). 친구 대신 '#방키'(admin rooms)면 그 방,
#                           단체방은 기본 꺼짐이라 schedule '#방키' on 으로 켬
#                선 전화·그림 화두: admin topics status | topics <친구> call on|off | topics <친구> pictures on|off
#                           | topics <친구> window 19:00-21:30 (디스코드 봇의 복사본으로 돎)
#   proactive <이름|#키|#방키> [--dry]  그 친구의 1:1 방(또는 그 방)에 선톡 한 개를 지금 보냄(시험용). --dry 면 만든 말만 보여 줌
#   report <저장할 파일.xlsx> [시간] [끝 시각]  지난 24시간(기본) 대화·임베딩·답에 들어간 기억·요약/메모를 엑셀로 받음
#                끝 시각 예: 2026-10-27T19:00+09:00 (비우면 지금). 서버엔 파일을 남기지 않음
#   sheet url|on|off|now|status  구글 시트에 최근 30일 기록을 5분마다 보냄(서버가 함, 노트북은 꺼져도 됨. tools/sheet.gs)
#                url: 시트 웹 앱 주소 넣기(화면엔 안 보임)와 한 번 보내 보기 / on·off: 5분마다 보내기와 시트 메뉴
#                '마롱이 > 지금 새로고침'(서버가 1분마다 물어봄) 켜기·끄기
#                now: 지금 한 번 보내기 / status: 타이머와 최근 결과
#   backup       DB 백업 파일을 서버의 /var/backups/marong 에 만듦(자동 백업은 하지 않음)
#   chat         서버에서 터미널로 마롱이와 대화(카카오 없이. 'terminal' 방으로 저장됨)
#   galaxy-test start|stop|status  통화 갤럭시 시험(기능 명세 7.1). start는 시험 파일만 서버의 ~/marong-galaxy-test 로
#                올리고 시험 서버(127.0.0.1)와 Cloudflare 임시 주소를 켬. sudo·다른 서비스는 건드리지 않음.
#                OpenAI 키는 서버의 ~/.config/marong-call/openai.key 에 넣어 둠(값은 화면에 안 보임, 켠 뒤에 넣어도 됨).
#                cloudflared는 서버의 PATH나 ~/.local/bin에서 찾음. 다른 곳이면 CLOUDFLARED=/서버의/절대/경로 를 앞에 붙임
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${MARONG_HOST:-ko-family}
DEST=/opt/marong
SSH=(ssh -o ServerAliveInterval=30)
AS_MARONG="sudo -u marong sh -c"

on_server() { "${SSH[@]}" "$HOST" "$@"; }

case "${1:-}" in
  install)
    tar -czf - --exclude .venv --exclude .env --exclude .cache --exclude .git --exclude __pycache__ \
        --exclude tests --exclude '*.db*' . |
      on_server 'rm -rf ~/marong-src && mkdir ~/marong-src && tar -xzf - -C ~/marong-src --warning=no-unknown-keyword'
    on_server 'cd ~/marong-src && bash deploy/setup-ubuntu.sh && sudo systemctl try-restart marong'
    ;;
  migrate-env)
    on_server "sudo python3 - $DEST/.env /opt/kakao-bot/.env" < deploy/migrate_env.py
    ;;
  env)
    "${SSH[@]}" -t "$HOST" "sudo -u marong nano $DEST/.env"
    ;;
  check)
    on_server "$AS_MARONG 'cd $DEST && .venv/bin/python run.py --check'"
    ;;
  switch)
    on_server "$AS_MARONG 'cd $DEST && .venv/bin/python run.py --check'" ||
      { echo "점검 실패라 바꾸지 않음(옛 봇은 그대로 돌고 있음)"; exit 1; }
    on_server 'if systemctl cat kakao-bot >/dev/null 2>&1; then sudo systemctl disable --now kakao-bot; fi
               sudo systemctl enable --now marong'
    sleep 5
    on_server 'systemctl is-active kakao-bot marong || true; sudo journalctl -u marong -n 20 --no-pager'
    echo "마롱이를 켬. 카톡으로 말을 걸어 보고, 로그는 bash deploy/ovh.sh logs"
    ;;
  rollback)
    on_server 'sudo systemctl disable --now marong && sudo systemctl enable --now kakao-bot && systemctl is-active kakao-bot'
    ;;
  restart) on_server 'sudo systemctl restart marong && systemctl is-active marong' ;;
  stop) on_server 'sudo systemctl disable --now marong' && echo "마롱이를 끔" ;;
  status) on_server 'systemctl is-active postgresql marong kakao-bot || true' ;;
  logs) "${SSH[@]}" -t "$HOST" 'sudo journalctl -u marong -f -n 50' ;;
  prompt)
    for f in prompt.md welcome.txt; do
      if [ -f "$f" ]; then
        on_server "$AS_MARONG 'cat > $DEST/$f.tmp && mv $DEST/$f.tmp $DEST/$f'" < "$f"
        echo "올림: $f"
      fi
    done
    if [ -d knowledge ]; then
      # 폴더째 바꿔 끼움: 서버의 knowledge/ 가 이 폴더와 똑같아짐(여기서 지운 파일은 서버에서도 지워짐)
      tar -czf - knowledge |
        on_server "$AS_MARONG 'cd $DEST && rm -rf knowledge.new knowledge.old && mkdir knowledge.new &&
          tar -xzf - -C knowledge.new --strip-components=1 --warning=no-unknown-keyword &&
          { [ ! -d knowledge ] || mv knowledge knowledge.old; } && mv knowledge.new knowledge && rm -rf knowledge.old'"
      echo "올림: knowledge/"
    fi
    ;;
  admin)
    shift
    # topics(선 전화·그림 화두)는 디스코드 봇 코드에만 있어서 그 복사본(/opt/marong-discord)으로 돌림. 파이썬은 같은 venv
    where=$DEST
    if [ "${1:-}" = topics ]; then where=/opt/marong-discord; fi
    on_server "cd / && sudo -u marong $DEST/.venv/bin/python $where/tools/admin.py $(printf '%q ' "$@")"
    ;;
  report)
    out=${2:?"사용법: bash deploy/ovh.sh report <저장할 파일.xlsx> [시간] [끝 시각]"}
    args=(--hours "${3:-24}")
    if [ -n "${4:-}" ]; then args+=(--until "$4"); fi
    # 엑셀은 ssh 출력으로 바로 받음. 실패하면 반쯤 받은 파일을 지움
    if on_server "cd / && sudo -u marong $DEST/.venv/bin/python $DEST/tools/report.py $(printf '%q ' "${args[@]}")" > "$out.part"; then
      mv "$out.part" "$out"
      echo "저장: $out ($(wc -c < "$out" | tr -d ' ') 바이트)"
    else
      rm -f "$out.part"
      echo "리포트를 못 만듦(위 오류 참고)"
      exit 1
    fi
    ;;
  sheet)
    case "${2:-}" in
      url)
        # 웹 앱 주소는 비밀(아는 사람은 시트에 쓸 수 있음): 화면·명령줄·로그에 안 남게 ssh 입력으로만 보냄
        read -rsp "시트 웹 앱 주소(붙여 넣어도 화면엔 안 보임): " url
        echo
        url=$(printf '%s' "$url" | tr -d '[:space:]')
        case "$url" in
          https://script.google.com/*/exec) ;;
          *) echo "https://script.google.com/…/exec 모양의 웹 앱 주소가 아님(tools/sheet.gs 맨 위 설명 참고)"; exit 1 ;;
        esac
        # .env 는 새 파일(600)에 옮겨 쓰고 바꿔 끼움. 다른 줄은 그대로
        printf '%s\n' "$url" | on_server "$AS_MARONG 'cd $DEST && umask 077 && read -r u && test -s .env &&
          { grep -v -E \"^[[:space:]]*SHEET_URL[[:space:]]*=\" .env; test \$? -le 1; } > .env.new &&
          printf \"SHEET_URL=%s\\n\" \"\$u\" >> .env.new && mv .env.new .env || { rm -f .env.new; exit 1; }'"
        echo "넣음. 시트로 한 번 보내 봄:"
        on_server "cd / && sudo -u marong $DEST/.venv/bin/python $DEST/tools/report.py --sheet" ||
          { echo "못 보냄: 웹 앱 배포 설정(실행: 나, 액세스: 모든 사용자)과 주소를 확인"; exit 1; }
        echo "5분마다 보내려면: bash deploy/ovh.sh sheet on"
        ;;
      on)
        on_server "sudo test -f $DEST/deploy/marong-sheet-ask.timer || { echo '먼저 bash deploy/ovh.sh install'; exit 1; }
                   sudo -u marong grep -q '^SHEET_URL=https://script.google.com/' $DEST/.env ||
                     { echo '먼저 bash deploy/ovh.sh sheet url'; exit 1; }
                   sudo cp $DEST/deploy/marong-sheet.service $DEST/deploy/marong-sheet.timer \
                     $DEST/deploy/marong-sheet-ask.service $DEST/deploy/marong-sheet-ask.timer /etc/systemd/system/ &&
                   sudo systemctl daemon-reload && sudo systemctl enable --now marong-sheet.timer marong-sheet-ask.timer &&
                   systemctl list-timers 'marong-sheet*' --no-pager"
        ;;
      off)
        on_server 'sudo systemctl disable --now marong-sheet.timer marong-sheet-ask.timer' &&
          echo "시트 보내기와 '지금 새로고침'을 끔(시트 내용은 그대로)"
        ;;
      now)
        on_server 'systemctl cat marong-sheet.service >/dev/null 2>&1 || { echo "먼저 bash deploy/ovh.sh sheet on"; exit 1; }
                   t=$(date +%s); sudo systemctl start marong-sheet.service; rc=$?
                   sudo journalctl -u marong-sheet --since "@$t" --no-pager -o cat; exit $rc'
        ;;
      status)
        on_server 'echo "5분 갱신: $(systemctl is-active marong-sheet.timer 2>/dev/null) · 지금 새로고침(1분마다 물어봄): $(systemctl is-active marong-sheet-ask.timer 2>/dev/null)"
                   systemctl list-timers "marong-sheet*" --all --no-pager
                   sudo journalctl -u marong-sheet -u marong-sheet-ask -n 8 --no-pager -o short-iso'
        ;;
      *) echo "사용법: bash deploy/ovh.sh sheet url|on|off|now|status"; exit 1 ;;
    esac
    ;;
  backup)
    on_server 'sudo install -d -m 700 -o postgres -g postgres /var/backups/marong &&
               f=/var/backups/marong/marong-$(date +%Y%m%d-%H%M).dump &&
               sudo -u postgres pg_dump -Fc -f "$f" marong && sudo ls -lh "$f"'
    ;;
  proactive)
    shift
    on_server "$AS_MARONG 'cd $DEST && exec .venv/bin/python run.py --proactive \"\$@\"' _ $(printf '%q ' "$@")"
    ;;
  chat) "${SSH[@]}" -t "$HOST" "$AS_MARONG 'cd $DEST && .venv/bin/python run.py --chat'" ;;
  galaxy-test)
    sub=${2:-status}
    case "$sub" in start|stop|status) ;; *) echo "사용법: bash deploy/ovh.sh galaxy-test start|stop|status"; exit 1 ;; esac
    port=${MARONG_TEST_PORT:-8791}
    case "$port" in ''|*[!0-9]*) echo "MARONG_TEST_PORT는 숫자여야 해요"; exit 1 ;; esac
    # cloudflared가 서버의 PATH나 ~/.local/bin에 없으면 서버 안의 절대 경로를 CLOUDFLARED=… 로 줘요
    cf=${CLOUDFLARED:-}
    case "$cf" in ''|/*) ;; *) echo "CLOUDFLARED는 서버 안의 절대 경로여야 해요"; exit 1 ;; esac
    case "$cf" in *[!A-Za-z0-9/._-]*) echo "CLOUDFLARED 경로에는 영문·숫자·/._- 만 써 주세요"; exit 1 ;; esac
    if [ "$sub" = start ]; then
      tar -czf - --exclude __pycache__ tools/galaxy_test call_prompt.md marong/call/static/face/v1/01-neutral.webp |
        on_server 'rm -rf ~/marong-galaxy-test/src && mkdir -p ~/marong-galaxy-test/src &&
                   chmod 700 ~/marong-galaxy-test && tar -xzf - -C ~/marong-galaxy-test/src --warning=no-unknown-keyword'
    fi
    on_server "CLOUDFLARED=$cf MARONG_TEST_PORT=$port bash ~/marong-galaxy-test/src/tools/galaxy_test/run.sh $sub"
    ;;
  *) sed -n '2,32p' "$0"; exit 1 ;;
esac
