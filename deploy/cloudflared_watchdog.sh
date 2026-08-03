#!/usr/bin/env bash
# myWiki API named tunnel(api.mywiki.pe.kr) 유지 — cloudflared 프로세스가 죽어있으면 재시작한다.
# named tunnel이라 quick tunnel과 달리 URL이 고정이라 별도 URL 추적이 필요 없다.
#
# 사전 준비(VM에 1회, 레포에는 없음): ~/.cloudflared/cert.pem, mywiki-api 터널 생성 +
# route dns 완료, ~/.cloudflared/mywiki-api-config.yml에 tunnel id/credentials-file/ingress 기록.
#
# 크론(예시): * * * * * bash ~/projects/myWiki/deploy/cloudflared_watchdog.sh >> /tmp/mywiki_cloudflared_watchdog.log 2>&1
set -euo pipefail

CONFIG="$HOME/.cloudflared/mywiki-api-config.yml"
LOG="/tmp/mywiki_cloudflared.log"
PID_FILE="$HOME/.local/state/mywiki/cloudflared.pid"
LOCK="/tmp/mywiki_cloudflared_watchdog.lock"
mkdir -p "$(dirname "$PID_FILE")"

exec 9>"$LOCK"
flock -n 9 || exit 0

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    exit 0
fi

echo "[$(date '+%F %T')] cloudflared 미실행 — mywiki-api 터널 재시작"
nohup cloudflared tunnel --config "$CONFIG" run mywiki-api >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
