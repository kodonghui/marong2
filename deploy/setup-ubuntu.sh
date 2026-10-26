#!/usr/bin/env bash
# Ubuntu 24.04 서버에 마롱이를 설치한다: Postgres 16 + pgvector, marong 계정, /opt/marong, systemd.
# 여러 번 실행해도 안전하다. 봇을 켜지는 않는다(켜기는 노트북에서 bash deploy/ovh.sh switch).
# 사용: 이 폴더를 서버에 올린 뒤  bash deploy/setup-ubuntu.sh   (보통은 노트북에서 bash deploy/ovh.sh install)
set -euo pipefail
DEST=/opt/marong

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
sudo -E apt-get update -y
sudo -E apt-get install -y postgresql-16 postgresql-16-pgvector python3-venv rsync
sudo systemctl enable --now postgresql

id marong >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir "$DEST" --shell /usr/sbin/nologin marong

# DB: marong 데이터베이스 + 표·권한(봇 계정은 지우기·고치기 권한 없음). 이미 있으면 그대로 두고 권한만 다시 맞춤
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'marong'" | grep -q 1; then
  sudo -u postgres createdb marong
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d marong < marong/schema.sql

# 코드. 서버에서 고친 prompt.md·welcome.txt·knowledge/ 는 덮어쓰지 않음(처음 설치 때만 복사).
# 내용을 바꿀 때는 노트북에서 bash deploy/ovh.sh prompt
KEEP=()
for f in prompt.md welcome.txt knowledge; do
  if sudo test -e "$DEST/$f"; then KEEP+=(--exclude "/$f"); fi
done
sudo rsync -a --exclude .venv --exclude .env --exclude .cache --exclude .git --exclude tests \
  ${KEEP[@]+"${KEEP[@]}"} ./ "$DEST"/
sudo chown -R marong:marong "$DEST"
sudo -u marong python3 -m venv "$DEST/.venv"
sudo -u marong "$DEST/.venv/bin/pip" install -q --disable-pip-version-check -r "$DEST/requirements.txt"

if ! sudo test -f "$DEST/.env"; then
  sudo -u marong sh -c "umask 077 && cp '$DEST/.env.example' '$DEST/.env'"
  echo "→ $DEST/.env 를 만들었어요. 값 넣기: 노트북에서 bash deploy/ovh.sh migrate-env (또는 env)"
fi
sudo chmod 600 "$DEST/.env"
sudo cp deploy/marong.service /etc/systemd/system/marong.service
# 시트 보내기(bash deploy/ovh.sh sheet on)를 켠 적 있는 서버면 그 유닛도 새것으로. 켠 적 없으면 그대로 둠
if [ -f /etc/systemd/system/marong-sheet.timer ]; then
  sudo cp deploy/marong-sheet.service deploy/marong-sheet.timer /etc/systemd/system/
fi
sudo systemctl daemon-reload
echo "설치 끝(봇은 켜지 않음). 다음: bash deploy/ovh.sh check"
