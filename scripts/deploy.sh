#!/usr/bin/env bash
# Deploy NuvoDesk to vmslave (10.1.50.97)
set -e

VMSLAVE="tenacitas@10.1.50.97"
PASS="openclaw"
REMOTE_DIR="/srv/openclaw/projects/nuvodesk"
TMP="/tmp/nuvodesk-sync"

echo "=== Syncing files to $VMSLAVE:$TMP ==="
rsync -az --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  --exclude 'android-app/' --exclude 'data/' \
  /home/admingemini/nuvodesk/ \
  $VMSLAVE:$TMP/

echo "=== Moving to $REMOTE_DIR ==="
ssh $VMSLAVE "echo '$PASS' | sudo -S rsync -a --exclude 'data/' $TMP/ $REMOTE_DIR/ && \
  echo '$PASS' | sudo -S mkdir -p $REMOTE_DIR/data && \
  echo '$PASS' | sudo -S chown -R www-data:www-data $REMOTE_DIR && \
  echo '$PASS' | sudo -S cp $TMP/nuvodesk.service /etc/systemd/system/ && \
  echo '$PASS' | sudo -S systemctl daemon-reload && \
  echo '$PASS' | sudo -S systemctl enable nuvodesk && \
  echo '$PASS' | sudo -S systemctl restart nuvodesk && \
  sleep 1 && \
  echo '$PASS' | sudo -S systemctl is-active nuvodesk"

echo "=== Checking nginx ==="
ssh $VMSLAVE "grep -r 'nuvodesk' /etc/nginx/sites-enabled/ 2>/dev/null | head -3 || echo 'Nginx: añadir location manualmente'"

echo "=== HTTP check ==="
sleep 1
curl -s -o /dev/null -w "ROOT:%{http_code}\n" http://10.1.50.97/nuvodesk/ || \
  curl -s -o /dev/null -w "DIRECT:%{http_code}\n" http://10.1.50.97:8014/ || true

echo "=== Done ==="
