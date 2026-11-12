#!/usr/bin/env bash
# 서버(ko-family)에서 갤럭시 시험 서버와 Cloudflare 임시 터널을 켜고 끕니다. sudo를 쓰지 않고,
# 다른 서비스(마롱이 카톡 봇, 필받음 등)와 그 설정은 건드리지 않아요.
#   bash run.sh start    켜고 시험 주소를 보여 줌(켜져 있으면 끄고 다시 켬)
#   bash run.sh stop     끄기
#   bash run.sh status   상태와 주소
# 시험 서버는 TEST_RUN_HOURS(기본 8시간) 뒤 스스로 끝나고, 그러면 터널도 꺼져요.
# cloudflared는 CLOUDFLARED=/절대/경로, PATH, ~/.local/bin/cloudflared 순서로 찾아요.
set -euo pipefail
cd "$(dirname "$0")"
STATE=${TEST_LOG_DIR:-$HOME/marong-galaxy-test}
PORT=${MARONG_TEST_PORT:-8791}
KEY_FILE=${OPENAI_KEY_FILE:-$HOME/.config/marong-call/openai.key}
mkdir -p "$STATE"
chmod 700 "$STATE"

alive() { [ -f "$STATE/$1.pid" ] && kill -0 "$(cat "$STATE/$1.pid")" 2>/dev/null; }
stop_all() {
  for f in tunnel server; do
    if alive "$f"; then kill "$(cat "$STATE/$f.pid")" 2>/dev/null || true; fi
    rm -f "$STATE/$f.pid"
  done
}
health() { curl -fsS -m 3 "http://127.0.0.1:$PORT/healthz"; }

start_tunnel() {
  : >"$STATE/tunnel.out"
  # 필받음 터널의 설정 파일(~/.cloudflared, /etc/cloudflared)을 읽지 않도록 늘 이 빈 설정만 줘요.
  # 임시 터널(trycloudflare)은 계정이 필요 없어요.
  printf 'no-autoupdate: true\n' >"$STATE/cloudflared.yml"
  nohup "$CF" tunnel --config "$STATE/cloudflared.yml" --no-autoupdate --url "http://127.0.0.1:$PORT" \
    >"$STATE/tunnel.out" 2>&1 &
  echo $! >"$STATE/tunnel.pid"
  URL=""
  for _ in $(seq 1 45); do
    URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$STATE/tunnel.out" | head -1 || true)
    [ -n "$URL" ] && return 0
    alive tunnel || return 1
    sleep 1
  done
  return 1
}

case "${1:-start}" in
  start)
    if [ -s "$KEY_FILE" ]; then
      chmod 600 "$KEY_FILE"
    else
      echo "OpenAI 키 파일이 아직 없어요: $KEY_FILE (가짜 통화 ?fake=1은 돼요. 키를 넣으면 다시 켜지 않아도 진짜 통화가 돼요)"
    fi
    PY=$(command -v python3) || { echo "python3가 없어요"; exit 1; }
    CF=${CLOUDFLARED:-}
    if [ -z "$CF" ]; then
      CF=$(command -v cloudflared || true)
      [ -n "$CF" ] || CF=$HOME/.local/bin/cloudflared
    fi
    case "$CF" in /*) ;; *) echo "cloudflared는 절대 경로로 알려 주세요: $CF"; exit 1 ;; esac
    [ -x "$CF" ] || { echo "cloudflared가 없어요: $CF (README의 cloudflared 안내를 보거나 CLOUDFLARED=/절대/경로 로 알려 주세요)"; exit 1; }
    stop_all
    # 키는 이 키 파일에서만 읽어요(셸에 OPENAI_API_KEY가 있어도 쓰지 않게)
    env -u OPENAI_API_KEY TEST_BIND="127.0.0.1:$PORT" OPENAI_KEY_FILE="$KEY_FILE" TEST_LOG_DIR="$STATE" \
      nohup "$PY" -I server.py >"$STATE/server.out" 2>&1 &
    echo $! >"$STATE/server.pid"
    for _ in $(seq 1 20); do health >/dev/null 2>&1 && break; sleep 0.5; done
    if ! health; then
      echo "시험 서버가 안 켜졌어요(포트 $PORT를 쓰는 다른 프로그램이 있으면 MARONG_TEST_PORT로 바꿔요):"
      tail -5 "$STATE/server.out"
      stop_all
      exit 1
    fi
    echo
    start_tunnel || { echo "임시 주소를 못 받았어요:"; tail -8 "$STATE/tunnel.out"; stop_all; exit 1; }
    echo "$URL" >"$STATE/url.txt"
    # 시험 서버가 스스로 끝나면 터널도 꺼요
    nohup bash -c 'while kill -0 "$1" 2>/dev/null; do sleep 10; done; kill "$2" 2>/dev/null' _ \
      "$(cat "$STATE/server.pid")" "$(cat "$STATE/tunnel.pid")" >/dev/null 2>&1 &
    echo "시험 주소: $URL"
    ;;
  stop)
    stop_all
    echo "껐어요"
    ;;
  status)
    if alive server; then echo "시험 서버: 켜짐 $(health 2>/dev/null || true)"; else echo "시험 서버: 꺼짐"; fi
    if alive tunnel; then echo "터널: 켜짐 $(cat "$STATE/url.txt" 2>/dev/null || true)"; else echo "터널: 꺼짐"; fi
    ;;
  *)
    echo "사용법: bash run.sh start|stop|status"
    exit 2
    ;;
esac
