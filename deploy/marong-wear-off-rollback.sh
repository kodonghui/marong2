#!/bin/bash
set -euo pipefail
B=/home/opc/marong-deploy/20261128-marong-wear-off
if [ "$(id -u)" -ne 0 ]; then echo 'STOP: root required'; exit 2; fi
python3 "$B/marong-wear-off.py" rollback
systemctl restart marong-app.service
systemctl is-active --quiet marong-app.service
printf '%s\n' 'app restored and active; database tables remain'
