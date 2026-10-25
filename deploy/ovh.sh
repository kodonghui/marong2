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
#   admin …      기록 보기(읽기만): admin people | admin rooms | admin show <이름 또는 #키> [개수] | admin stats
#   proactive <이름 또는 #키> [--dry]  그 친구의 1:1 방에 선톡 한 개를 지금 보냄(시험용). --dry 면 만든 말만 보여 줌
#   backup       DB 백업 파일을 서버의 /var/backups/marong 에 만듦(자동 백업은 하지 않음)
#   chat         서버에서 터미널로 마롱이와 대화(카카오 없이. 'terminal' 방으로 저장됨)
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
    on_server "cd / && sudo -u marong $DEST/.venv/bin/python $DEST/tools/admin.py $(printf '%q ' "$@")"
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
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
