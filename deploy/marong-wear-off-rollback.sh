#!/bin/bash
set -euo pipefail
B=/home/opc/marong-deploy/20261128-marong-wear-off
if [ "$(id -u)" -ne 0 ]; then echo 'STOP: root required'; exit 2; fi
python3 "$B/marong-wear-off.py" rollback
changelog_error=0
if [ -f "$B/changelog.json" ]; then
  (cd /opt/marong-app && flock /run/lock/marong-changelog.lock /opt/marong/.venv/bin/python -m marong.admin_changes rollback 20261128-marong-wear-off /home/opc/marong-deploy) || changelog_error=1
fi
systemctl restart marong-app.service
systemctl is-active --quiet marong-app.service
if [ "$changelog_error" -ne 0 ]; then echo 'STOP: app restored; changelog rollback needs inspection'; exit 2; fi
printf '%s\n' 'app restored and active; database tables remain'
