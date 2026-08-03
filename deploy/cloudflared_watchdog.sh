#!/usr/bin/env bash
# myWiki API quick 터널 유지 — cloudflared 프로세스가 죽어있으면 재시작하고
# 새 trycloudflare URL을 URL_FILE에 기록한다.
#
# Vercel의 VITE_API_BASE_URL은 이 스크립트가 자동으로 갱신하지 않는다 — 로그에
# "새 URL"이 찍히면 URL_FILE 값을 확인해서 Vercel 환경변수에 수동 반영해야 한다.
#
# 크론(예시): * * * * * bash ~/projects/myWiki/deploy/cloudflared_watchdog.sh >> /tmp/mywiki_cloudflared_watchdog.log 2>&1
set -euo pipefail

PORT="${MYWIKI_API_PORT:-8010}"
LOG="/tmp/mywiki_cloudflared.log"
PID_FILE="$HOME/.local/state/mywiki/cloudflared.pid"
URL_FILE="$HOME/.cache/mywiki_api_tunnel_url.txt"
LOCK="/tmp/mywiki_cloudflared_watchdog.lock"
mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$URL_FILE")"

exec 9>"$LOCK"
flock -n 9 || exit 0

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    exit 0
fi

echo "[$(date '+%F %T')] cloudflared 미실행 — 터널 재시작"
: > "$LOG"
nohup cloudflared tunnel --url "http://localhost:${PORT}" >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"

NEW=""
for _ in $(seq 1 60); do
    NEW=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" 2>/dev/null | tail -1)
    [ -n "$NEW" ] && break
    sleep 2
done
if [ -z "$NEW" ]; then
    echo "  URL 확보 실패(120s)"
    exit 1
fi

CUR=$(cat "$URL_FILE" 2>/dev/null || echo "")
echo "$NEW" > "$URL_FILE"
if [ "$NEW" != "$CUR" ]; then
    echo "  새 URL: $NEW (이전: ${CUR:-없음}) — Vercel VITE_API_BASE_URL 수동 갱신 필요"
fi
