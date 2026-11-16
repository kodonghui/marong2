#!/usr/bin/env bash
# 노트북(Git Bash, 이 저장소 폴더)에서 통화 엔진 측정을 마롱이 서버에서 돌리고, 결과 묶음을 측정 브랜치에 올려요.
# 이 폴더의 작업 트리·현재 브랜치·인덱스는 건드리지 않아요(브랜치에서 바로 꺼내 쓰고, 결과는 임시 인덱스로 커밋).
#
#   git fetch origin claude/project-thread-p4wjk1
#   git show origin/claude/project-thread-p4wjk1:tools/voice_bench/run_from_laptop.sh | bash -s -- start
#   ... | bash -s -- status     # 진행 중이면 RUNNING과 마지막 줄들, 끝나면 DONE
#   ... | bash -s -- collect    # 끝난 결과(results.tar.gz)를 받아 브랜치의 tools/voice_bench/server-results/ 에 커밋·푸시
#
# 서버에서는 ~/marong-voice-bench/<시각>/ 안에만 써요. sudo를 쓰지 않고 운영 서비스·설정은 건드리지 않아요.
# 키는 서버의 ~/.config/marong-call/ 파일을 서버 안에서만 읽어요(이 스크립트는 키를 읽거나 옮기지 않아요).
set -euo pipefail
BR=${VOICE_BENCH_BRANCH:-claude/project-thread-p4wjk1}
HOST=${MARONG_HOST:-ko-family}
SSH=(ssh -o ServerAliveInterval=30)
cmd=${1:-status}

latest() { "${SSH[@]}" "$HOST" 'cat ~/marong-voice-bench/LATEST'; }

case "$cmd" in
  start)
    git fetch -q origin "$BR"
    ref=$(git rev-parse "origin/$BR")
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    dir="marong-voice-bench/$stamp"
    git archive "$ref" tools/voice_bench/bench_server.py tools/voice_bench/inputs |
      "${SSH[@]}" "$HOST" "mkdir -p ~/$dir && tar -x -C ~/$dir && echo $ref > ~/$dir/COMMIT && echo $dir > ~/marong-voice-bench/LATEST"
    "${SSH[@]}" "$HOST" "cd ~/$dir/tools/voice_bench && PY=\$HOME/marong-vertex-test/venv-memory2/bin/python && { [ -x \"\$PY\" ] || PY=python3; } && \"\$PY\" -I -c 'import sys; print(\"python\", sys.version.split()[0])' && (nohup \"\$PY\" -I bench_server.py all > run.log 2>&1 < /dev/null &) && echo started ~/$dir"
    ;;
  status)
    dir=$(latest)
    "${SSH[@]}" "$HOST" "cd ~/$dir/tools/voice_bench && tail -n 6 run.log; if [ -f results/DONE ]; then echo DONE; else echo RUNNING; fi"
    ;;
  collect)
    dir=$(latest)
    stamp=${dir##*/}
    tmp=$(mktemp -d)
    "${SSH[@]}" "$HOST" "cd ~/$dir/tools/voice_bench && test -f results/DONE && cat results.tar.gz" > "$tmp/results.tar.gz"
    test -s "$tmp/results.tar.gz"
    git fetch -q origin "$BR"
    ref=$(git rev-parse "origin/$BR")
    blob=$(git hash-object -w "$tmp/results.tar.gz")
    export GIT_INDEX_FILE="$tmp/index"
    git read-tree "$ref"
    git update-index --add --cacheinfo "100644,$blob,tools/voice_bench/server-results/$stamp.tar.gz"
    tree=$(git write-tree)
    unset GIT_INDEX_FILE
    msg="Voice bench: results from the Marong server, $stamp"
    msg="$msg"$'\n\n'"Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"$'\n'"Claude-Session: https://claude.ai/code/session_01GTF2haPydzNt9wvJ82Esuf"
    commit=$(git commit-tree "$tree" -p "$ref" -m "$msg")
    git push origin "$commit:refs/heads/$BR"
    rm -rf "$tmp"
    echo "pushed $commit tools/voice_bench/server-results/$stamp.tar.gz"
    ;;
  *)
    echo "usage: start | status | collect" >&2
    exit 2
    ;;
esac
